"""
Edge cases in what the caller passes and what the exchange does back.

`_execute_raw_call` approves the exchange for at most the caller's cap, `raw_call`s it, and
then judges the result purely by the change in the zap's own token balance. The call
itself is unchecked: no code-size check and no return value, which is normal for an
aggregator but means the only thing
separating "the swap happened" from "nothing happened" is the balance comparison the
callbacks make afterwards. These tests pin that separation from both sides, plus the
argument shapes nothing else covers.
"""

import boa
import pytest

from tests.utils.deployers import MALICIOUS_ROUTER_DEPLOYER

from tests.e2e.zaps.transient_leverage_zap.conftest import (
    approve_zap,
    collateral_from_borrowed,
    make_deposit_calldata,
)

N = 10


@pytest.fixture
def borrower(controller, collateral_token, borrowed_token, leverage_zap):
    user = boa.env.generate_address()
    boa.deal(collateral_token, user, 10**6 * 10 ** collateral_token.decimals())
    boa.deal(borrowed_token, user, 10**6 * 10 ** borrowed_token.decimals())
    approve_zap(user, controller, leverage_zap, collateral_token, borrowed_token)
    return user


@pytest.fixture
def deposit(borrowed_token, collateral_token, price_oracle, controller_id):
    """Sizes a standard leveraged deposit and builds its swap arguments."""

    def _build(router, min_recv=None):
        bd = borrowed_token.decimals()
        cd = collateral_token.decimals()
        d_debt = 3000 * 10**bd
        collateral_out = collateral_from_borrowed(d_debt, price_oracle.price(), bd, cd)
        calldata = make_deposit_calldata(
            controller_id,
            collateral_out * 999 // 1000 if min_recv is None else min_recv,
            router,
            borrowed_token,
            collateral_token,
            d_debt,
            collateral_out,
        )
        return d_debt, collateral_out, calldata

    return _build


# ---------------------------------------------------------------------------
# Exchanges that do not swap
# ---------------------------------------------------------------------------


def test_whitelisted_address_without_code_is_caught_by_slippage(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    deposit,
    controller_id,
    admin,
):
    """
    A whitelisted address with no code at all - a typo in a `set_exchange` call, or a
    router that has since been self-destructed. `raw_call` to an account without code
    succeeds and returns nothing, so nothing at the EVM level marks this as a failure;
    the borrowed tokens simply sit in the zap.

    The slippage check is what turns that into a revert, which is why `min_recv` is the
    caller's only real protection here and not just a price bound.
    """
    empty_exchange = boa.env.generate_address()
    with boa.env.prank(admin):
        leverage_zap.set_exchange(empty_exchange, True)
    assert boa.env.get_code(empty_exchange) == b""

    cd = collateral_token.decimals()
    d_debt, collateral_out, (min_recv, _, exchange_calldata) = deposit(dummy_router)

    with boa.env.prank(borrower):
        with boa.reverts("Slippage"):
            leverage_zap.create_loan(
                controller_id,
                2 * 10**cd,
                d_debt,
                N,
                min_recv,
                empty_exchange,
                exchange_calldata,
            )

    assert not controller.loan_exists(borrower)
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_exchange_revert_is_not_swallowed(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    deposit,
    controller_id,
    admin,
):
    """
    The other direction: `raw_call` is made without `revert_on_failure=False`, so an
    exchange that reverts takes the whole operation down and the reason reaches the
    caller rather than being reported as a slippage failure.
    """
    router = MALICIOUS_ROUTER_DEPLOYER.deploy()
    boa.deal(borrowed_token, router.address, 10**9 * 10 ** borrowed_token.decimals())
    boa.deal(
        collateral_token, router.address, 10**9 * 10 ** collateral_token.decimals()
    )
    router.set_should_revert(True)
    with boa.env.prank(admin):
        leverage_zap.set_exchange(router.address, True)

    cd = collateral_token.decimals()
    d_debt, collateral_out, calldata = deposit(router)

    with boa.env.prank(borrower):
        with boa.reverts("router failure"):
            leverage_zap.create_loan(controller_id, 2 * 10**cd, d_debt, N, *calldata)

    assert not controller.loan_exists(borrower)
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


# ---------------------------------------------------------------------------
# Argument shapes
# ---------------------------------------------------------------------------


def test_unknown_controller_id_reverts(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    deposit,
    market_type,
    factory,
    mint_factory,
):
    """
    The market is looked up by index in the factory, and an index past the end resolves
    to no controller at all. The call has to die there.

    It dies on the very first `staticcall` into the empty address, before reaching
    `_stash`'s `_controller != empty(address)` guard - so that guard is defence in
    depth for a factory returning something non-empty and wrong, not the thing catching
    a bad index.
    """
    cd = collateral_token.decimals()
    d_debt, collateral_out, calldata = deposit(dummy_router)

    if market_type == "lending":
        unknown_id = factory.market_count() + 1
    else:
        unknown_id = mint_factory.n_collaterals() + 1

    with boa.env.prank(borrower):
        with boa.reverts():
            leverage_zap.create_loan(unknown_id, 2 * 10**cd, d_debt, N, *calldata)

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_create_loan_with_no_collateral_of_their_own_reverts(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    deposit,
    controller_id,
):
    """
    Leverage with nothing of one's own cannot work: at a fair price the swap returns
    collateral worth exactly the debt that bought it, so the position would open at
    100% LTV. The controller rejects it on health.

    Worth pinning because the arguments are perfectly well-formed and the zap gets all
    the way through the swap before the answer comes back - and because `_collateral`
    of zero is the one path where `tkn.transfer_from` is skipped entirely, leaving
    `stashed_held` to be whatever the zap already held.
    """
    d_debt, collateral_out, calldata = deposit(dummy_router)
    collateral_before = collateral_token.balanceOf(borrower)
    borrowed_before = borrowed_token.balanceOf(borrower)

    with boa.env.prank(borrower):
        with boa.reverts():
            leverage_zap.create_loan(controller_id, 0, d_debt, N, *calldata)

    assert not controller.loan_exists(borrower)
    assert collateral_token.balanceOf(borrower) == collateral_before
    assert borrowed_token.balanceOf(borrower) == borrowed_before
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


def test_borrow_more_with_no_collateral_and_dust_in_the_zap(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    deposit,
    controller_id,
):
    """
    `_collateral` of zero on an existing position, with collateral dust already in the
    zap. Nothing is pulled from the caller, so `stashed_held` is the dust alone - and
    the dust must still be excluded from the swap output rather than credited to the
    position, then handed back at the end.

    test_dust.py covers dust on `create_loan`, where `stashed_held` is dominated by the
    caller's own deposit and a mistake would be much harder to see.
    """
    borrower = open_position()
    cd = collateral_token.decimals()
    dust = 5 * 10**cd
    state0 = controller.user_state(borrower)
    d_debt, collateral_out, calldata = deposit(dummy_router)

    boa.deal(collateral_token, leverage_zap.address, dust)
    collateral_before = collateral_token.balanceOf(borrower)

    with boa.env.prank(borrower):
        leverage_zap.borrow_more(controller_id, 0, d_debt, *calldata)

    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] + collateral_out  # the dust was not added
    assert state1[2] == state0[2] + d_debt
    assert collateral_token.balanceOf(borrower) == collateral_before + dust
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


def test_create_loan_with_zero_min_recv(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    deposit,
    controller_id,
):
    """
    `min_recv` of zero waives the check entirely. It is a legitimate thing to pass, so
    it must not be mistaken for "unset" and rejected - the caller simply gets whatever
    the exchange returns.
    """
    cd = collateral_token.decimals()
    d_debt, collateral_out, calldata = deposit(dummy_router, min_recv=0)

    with boa.env.prank(borrower):
        leverage_zap.create_loan(controller_id, 2 * 10**cd, d_debt, N, *calldata)

    state = controller.user_state(borrower)
    assert state[0] == 2 * 10**cd + collateral_out
    assert state[2] == d_debt


# ---------------------------------------------------------------------------
# Dust on the borrowed side of a deposit
# ---------------------------------------------------------------------------


def test_deposit_borrowed_dust_refunded_to_caller(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    deposit,
    controller_id,
):
    """
    The mirror of `test_deposit_collateral_dust_flushed_to_user`: borrowed tokens
    already sitting in the zap. `stashed_held` is taken from the collateral side during
    a deposit, so borrowed dust cannot distort the swap measurement - it just has to
    leave with the caller at the end rather than stay for whoever calls next.
    """
    cd = collateral_token.decimals()
    d_debt, collateral_out, calldata = deposit(dummy_router)
    dust = 250 * 10 ** borrowed_token.decimals()

    boa.deal(borrowed_token, leverage_zap.address, dust)
    borrowed_before = borrowed_token.balanceOf(borrower)

    with boa.env.prank(borrower):
        leverage_zap.create_loan(controller_id, 2 * 10**cd, d_debt, N, *calldata)

    # The whole debt was spent on the swap, so the caller's gain is exactly the dust
    assert borrowed_token.balanceOf(borrower) == borrowed_before + dust
    assert controller.user_state(borrower)[0] == 2 * 10**cd + collateral_out
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0
