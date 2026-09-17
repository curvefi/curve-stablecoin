"""
Tests for the guards that protect the transient stash while a whitelisted exchange is
on the stack.

`raw_call`-ing an exchange from `_execute_raw_call` hands control to another contract
at the worst possible moment: the stash is populated, the zap is holding the
user's parked collateral plus the freshly borrowed tokens, and it has standing
approvals on both the controller and - for the token being sold - the exchange itself.
The exchanges are whitelisted, but a whitelist entry is a router that can be upgraded,
proxied, or compromised, so the guards have to hold on their own:

  * `_stash` refuses to overwrite a populated stash ("Reentrancy"), which is what stops
    an exchange from calling an entry point again,
  * `_stashed_controller` refuses any caller that is not the controller of the call in
    flight ("wrong controller"), which is what stops anyone from driving the callbacks
    through a controller of their own choosing, and
  * the two callbacks share Vyper's global `@nonreentrant` lock.

Those last two turn out to divide the work differently than the contract's comments
suggest, and the tests below say which one is actually load-bearing where: while a
callback is running the lock rejects everything before the authentication is reached,
so "wrong controller" is the guard for calls arriving from outside an operation - the
case an attacker can reach for free, since the controller's `_callbacker` argument is
public.

Every test drives the honest operation through a router that attacks mid-swap. Where
the attack's revert is caught by the router, the test additionally asserts that the
honest operation completed untouched - a rejected attack must roll back cleanly rather
than leave the position or the zap's balances damaged.
"""

import boa
import pytest
from boa import BoaError
from eth_utils import keccak

from tests.utils.deployers import MALICIOUS_ROUTER_DEPLOYER

from tests.e2e.zaps.transient_leverage_zap.conftest import (
    approve_zap,
    borrowed_from_collateral,
    collateral_from_borrowed,
    make_deposit_calldata,
    make_repay_calldata,
)

N = 10


@pytest.fixture(scope="module")
def malicious_router(borrowed_token, collateral_token, leverage_zap, admin):
    """A whitelisted exchange that misbehaves while the zap has it on the stack."""
    router = MALICIOUS_ROUTER_DEPLOYER.deploy()
    boa.deal(borrowed_token, router.address, 10**9 * 10 ** borrowed_token.decimals())
    boa.deal(
        collateral_token, router.address, 10**9 * 10 ** collateral_token.decimals()
    )
    with boa.env.prank(admin):
        leverage_zap.set_exchange(router.address, True)
    return router


@pytest.fixture
def borrower(controller, collateral_token, borrowed_token, leverage_zap):
    user = boa.env.generate_address()
    boa.deal(collateral_token, user, 10**6 * 10 ** collateral_token.decimals())
    boa.deal(borrowed_token, user, 10**6 * 10 ** borrowed_token.decimals())
    approve_zap(user, controller, leverage_zap, collateral_token, borrowed_token)
    return user


@pytest.fixture
def deposit_swap(collateral_token, borrowed_token, price_oracle, controller_id):
    """Build the create_loan/borrow_more swap arguments for a given router."""

    def _build(router, d_debt, min_recv_bps=999):
        bd = borrowed_token.decimals()
        cd = collateral_token.decimals()
        collateral_out = collateral_from_borrowed(d_debt, price_oracle.price(), bd, cd)
        calldata = make_deposit_calldata(
            controller_id,
            collateral_out * min_recv_bps // 1000,
            router,
            borrowed_token,
            collateral_token,
            d_debt,
            collateral_out,
        )
        return collateral_out, calldata

    return _build


# ---------------------------------------------------------------------------
# Re-entering an entry point
# ---------------------------------------------------------------------------


def test_exchange_reentering_create_loan_reverts(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    malicious_router,
    deposit_swap,
    controller_id,
):
    """
    The exchange calls `create_loan` again from inside `callback_deposit`. The stash of
    the call in flight is still populated, so `_stash` rejects the second one.

    The re-entrant call asks for zero collateral on purpose: `tkn.transfer_from` skips
    zero amounts, so nothing but the guard itself can stop it before the stash is
    overwritten.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    d_debt = 3000 * 10**bd
    collateral_out, calldata = deposit_swap(malicious_router, d_debt)

    reentrant_call = leverage_zap.create_loan.prepare_calldata(
        controller_id, 0, 10**bd, N, 0, malicious_router.address, b""
    )
    malicious_router.set_attack(leverage_zap.address, reentrant_call)

    with boa.env.prank(borrower):
        with boa.reverts("Reentrancy"):
            leverage_zap.create_loan(controller_id, 2 * 10**cd, d_debt, N, *calldata)

    assert not controller.loan_exists(borrower)
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


def test_exchange_reentering_repay_cannot_drain_in_flight_collateral(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    malicious_router,
    deposit_swap,
    controller_id,
):
    """
    The nastiest shape of the re-entrancy: `_repay` opens by sweeping the zap's entire
    collateral balance to `msg.sender`, and during `callback_deposit` that balance is
    the borrower's parked collateral plus the swap
    output. An exchange that re-enters `repay` would be sweeping the borrower's funds
    to itself.

    The sweep is never committed, but not because of `_stash`: before stashing, `_repay`
    reads `debt()` from the controller, which is still inside `create_loan` and locks its
    views (`# pragma nonreentrancy on`), so the sub-call reverts there and the sweep rolls
    back with it. The zap's own "Reentrancy" guard is a second layer this path never
    reaches (`test_exchange_reentering_repay_reverts` pins the actual guard). Here the
    router swallows that revert, so the test can prove the sub-call rolled back: the
    honest loan is created in full and the router ends up with exactly the collateral it
    sold, not a wei more.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    collateral_out, calldata = deposit_swap(malicious_router, d_debt)

    reentrant_call = leverage_zap.repay.prepare_calldata(
        controller_id, 0, 0, 0, malicious_router.address, b"", 2**255 - 1, False
    )
    malicious_router.set_attack(leverage_zap.address, reentrant_call)
    malicious_router.set_catch_attack(True)

    router_collateral_before = collateral_token.balanceOf(malicious_router.address)

    with boa.env.prank(borrower):
        leverage_zap.create_loan(controller_id, user_collateral, d_debt, N, *calldata)

    # The attack ran and was rejected
    assert malicious_router.attack_attempted() is True
    assert malicious_router.attack_succeeded() is False

    # The honest operation is unaffected: full position, nothing stranded
    assert controller.user_state(borrower)[0] == user_collateral + collateral_out
    assert controller.user_state(borrower)[2] == d_debt
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0

    # The router only ever gave collateral away - the sweep was rolled back
    assert (
        collateral_token.balanceOf(malicious_router.address)
        == router_collateral_before - collateral_out
    )


def test_exchange_reentering_repay_reverts(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    malicious_router,
    deposit_swap,
    controller_id,
):
    """
    Same attack as above with the revert left to bubble up, pinning which guard stops it.

    It is not the zap's `_stash` check: `_repay` asks the controller for the caller's
    `debt()` before stashing, and the controller - `# pragma nonreentrancy on`, which
    locks its views too - is still inside `create_loan`. That reverts without a reason
    and takes the collateral sweep down with it, so the innermost failing call is pinned
    instead.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    d_debt = 3000 * 10**bd
    collateral_out, calldata = deposit_swap(malicious_router, d_debt)

    reentrant_call = leverage_zap.repay.prepare_calldata(
        controller_id, 0, 0, 0, malicious_router.address, b"", 2**255 - 1, False
    )
    malicious_router.set_attack(leverage_zap.address, reentrant_call)

    with boa.env.prank(borrower):
        with pytest.raises(BoaError) as e:
            leverage_zap.create_loan(controller_id, 2 * 10**cd, d_debt, N, *calldata)

    frame = e.value.call_trace
    while failed := [child for child in frame.children if child.is_error]:
        frame = failed[-1]
    assert frame.address == controller.address
    assert frame.selector == keccak(text="debt(address)")[:4]

    assert not controller.loan_exists(borrower)
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


def test_exchange_reentering_borrow_more_reverts(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    malicious_router,
    deposit_swap,
    controller_id,
):
    """The guard covers `borrow_more` as well, which shares `callback_deposit`."""
    borrower = open_position()
    bd = borrowed_token.decimals()
    d_debt = 1000 * 10**bd
    collateral_out, calldata = deposit_swap(malicious_router, d_debt)

    reentrant_call = leverage_zap.borrow_more.prepare_calldata(
        controller_id, 0, 10**bd, 0, malicious_router.address, b""
    )
    malicious_router.set_attack(leverage_zap.address, reentrant_call)

    state0 = controller.user_state(borrower)
    with boa.env.prank(borrower):
        with boa.reverts("Reentrancy"):
            leverage_zap.borrow_more(controller_id, 0, d_debt, *calldata)

    assert controller.user_state(borrower) == state0


def test_exchange_reentering_entry_point_during_repay_reverts(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    malicious_router,
    controller_id,
    price_oracle,
):
    """Same guard from inside `callback_repay`."""
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    borrowed_out = borrowed_from_collateral(
        collateral_to_swap, price_oracle.price(), bd, cd
    )
    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        malicious_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    reentrant_call = leverage_zap.create_loan.prepare_calldata(
        controller_id, 0, 10**bd, N, 0, malicious_router.address, b""
    )
    malicious_router.set_attack(leverage_zap.address, reentrant_call)

    with boa.env.prank(borrower):
        with boa.reverts("Reentrancy"):
            leverage_zap.repay(controller_id, 0, *calldata)

    assert controller.user_state(borrower) == state0


# ---------------------------------------------------------------------------
# Reaching the callbacks directly
# ---------------------------------------------------------------------------


def test_controller_call_with_zap_as_callbacker_reverts(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    The controller's `_callbacker` argument is public: anyone can point a perfectly
    ordinary `create_loan` at this zap, and the callback then arrives from a genuine
    controller of the zap's own factory. That is the case `_stashed_controller` exists
    for - the stash is empty because no entry point of the zap started this call, so
    the caller is refused even though it is a real controller.

    Without that check the caller would be handing the zap borrowed tokens and having
    it run an arbitrary whitelisted exchange on their behalf.
    """
    attacker = boa.env.generate_address()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    boa.deal(collateral_token, attacker, 10 * 10**cd)
    with boa.env.prank(attacker):
        collateral_token.approve(controller.address, 2**256 - 1)
        with boa.reverts("wrong controller"):
            controller.create_loan(
                2 * 10**cd,
                1000 * 10**bd,
                N,
                attacker,
                leverage_zap.address,
                b"",
            )

    assert not controller.loan_exists(attacker)
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


def test_callback_deposit_from_exchange_is_rejected_by_both_guards(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    malicious_router,
    deposit_swap,
    controller_id,
):
    """
    An exchange cannot reach `callback_deposit`, and the two windows are closed by
    different things - worth pinning, because only one of them is documented on
    `_stashed_controller`:

      * outside any zap operation the stash is empty, so the authentication rejects the
        router with "wrong controller";
      * *during* `callback_deposit` the stash is populated and points at the controller,
        but the callback already holds Vyper's global `@nonreentrant` lock, so a second
        entry is refused before the authentication is reached at all. The revert carries
        no reason string, which is how the lock reverts.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    d_debt = 3000 * 10**bd
    collateral_out, calldata = deposit_swap(malicious_router, d_debt)

    # Outside an operation: the stash is empty
    with boa.env.prank(malicious_router.address):
        with boa.reverts("wrong controller"):
            leverage_zap.callback_deposit(malicious_router.address, 0, 0, 0, b"")

    # During the callback: the reentrancy lock, not the authentication
    attack = leverage_zap.callback_deposit.prepare_calldata(
        malicious_router.address, 0, 0, 0, b""
    )
    malicious_router.set_attack(leverage_zap.address, attack)

    with boa.env.prank(borrower):
        with boa.reverts():
            leverage_zap.create_loan(controller_id, 2 * 10**cd, d_debt, N, *calldata)

    assert not controller.loan_exists(borrower)
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


def test_callback_repay_from_exchange_is_rejected(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    malicious_router,
    controller_id,
    price_oracle,
):
    """
    `callback_repay` returns `[borrowed, collateral]` that the controller then pulls
    from the zap, so anything that could reach it mid-operation could redirect funds.
    The two callbacks share one lock, so an exchange cannot cross from one to the other
    either.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    borrowed_out = borrowed_from_collateral(
        collateral_to_swap, price_oracle.price(), bd, cd
    )
    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        malicious_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(malicious_router.address):
        with boa.reverts("wrong controller"):
            leverage_zap.callback_repay(malicious_router.address, 0, 0, 0, b"")

    # From inside callback_repay, reaching callback_deposit is locked out as well
    attack = leverage_zap.callback_deposit.prepare_calldata(
        malicious_router.address, 0, 0, 0, b""
    )
    malicious_router.set_attack(leverage_zap.address, attack)

    with boa.env.prank(borrower):
        with boa.reverts():
            leverage_zap.repay(controller_id, 0, *calldata)

    assert controller.user_state(borrower) == state0
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


# ---------------------------------------------------------------------------
# Re-entering through the stashed controller
# ---------------------------------------------------------------------------


def test_exchange_reentering_via_the_stashed_controller_is_rejected(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    malicious_router,
    deposit_swap,
    controller_id,
):
    """
    The one path where `_stashed_controller` cannot help: the exchange asks the *real*
    controller - the one the zap stashed - to run another leveraged `create_loan` with
    the zap as callbacker. The callback would then arrive from the stashed controller
    and authenticate.

    What actually stops it is a layer further out: the controller carries
    `# pragma nonreentrancy on`, and the zap's two callbacks share Vyper's global
    `@nonreentrant` lock. This test pins that the path stays closed - the router gets
    no loan and no funds - because the guard the contract documents is not the one
    doing the work here.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    collateral_out, calldata = deposit_swap(malicious_router, d_debt)

    # The router poses as a user of the controller, borrowing with the zap as callbacker
    with boa.env.prank(malicious_router.address):
        controller.approve(leverage_zap.address, True)
    attack = controller.create_loan.prepare_calldata(
        0, 10**bd, N, malicious_router.address, leverage_zap.address, b""
    )
    malicious_router.set_attack(controller.address, attack)
    malicious_router.set_catch_attack(True)

    router_borrowed_before = borrowed_token.balanceOf(malicious_router.address)

    with boa.env.prank(borrower):
        leverage_zap.create_loan(controller_id, user_collateral, d_debt, N, *calldata)

    assert malicious_router.attack_attempted() is True
    assert malicious_router.attack_succeeded() is False

    # No loan for the router, and it only received what it was paid for the swap
    assert not controller.loan_exists(malicious_router.address)
    assert (
        borrowed_token.balanceOf(malicious_router.address)
        == router_borrowed_before + d_debt
    )
    # The borrower's position is exactly what was asked for
    assert controller.user_state(borrower)[0] == user_collateral + collateral_out
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
