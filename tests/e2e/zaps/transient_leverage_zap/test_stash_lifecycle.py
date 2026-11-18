"""
Tests that the transient stash is per-call, not per-transaction.

Every other test in this suite makes exactly one zap call per transaction, which cannot
tell a working `_unstash` from a missing one: transient storage is wiped at the end of
the transaction anyway, so a stash that is never cleared still looks clean to the next
test. The failure only shows up when a second call happens inside the same transaction
- a batching contract, a multicall, a router - and that second call then runs against
the first call's exchange, calldata, min_recv or held balance.

`ZapBatcher` stands in for such a caller: it is the zap's `msg.sender`, so the loans
belong to it and the refunds come back to it.

Each test makes the two calls differ in every stashed field, and sizes them so that a
leaked stash cannot merely produce a different-but-plausible result: the first call's
`min_recv` is far above the second call's swap output, so reusing it reverts.
"""

import boa
import pytest

from tests.utils.constants import MAX_UINT256
from tests.utils.deployers import DUMMY_ROUTER_DEPLOYER, ZAP_BATCHER_DEPLOYER

from tests.e2e.zaps.transient_leverage_zap.conftest import (
    borrowed_from_collateral,
    collateral_from_borrowed,
    make_deposit_calldata,
    make_repay_calldata,
)

N = 10


@pytest.fixture(scope="module")
def second_router(borrowed_token, collateral_token, leverage_zap, admin):
    """A second whitelisted exchange, so the two calls in a batch cannot share one."""
    router = DUMMY_ROUTER_DEPLOYER.deploy()
    boa.deal(borrowed_token, router.address, 10**9 * 10 ** borrowed_token.decimals())
    boa.deal(
        collateral_token, router.address, 10**9 * 10 ** collateral_token.decimals()
    )
    with boa.env.prank(admin):
        leverage_zap.set_exchange(router.address, True)
    return router


@pytest.fixture
def batcher(controller, collateral_token, borrowed_token, leverage_zap):
    """A funded batching contract that has approved the zap the way a user would."""
    batcher = ZAP_BATCHER_DEPLOYER.deploy()
    boa.deal(
        collateral_token, batcher.address, 10**6 * 10 ** collateral_token.decimals()
    )
    boa.deal(borrowed_token, batcher.address, 10**6 * 10 ** borrowed_token.decimals())
    batcher.execute(
        [collateral_token.address, borrowed_token.address, controller.address],
        [
            collateral_token.approve.prepare_calldata(
                leverage_zap.address, MAX_UINT256
            ),
            borrowed_token.approve.prepare_calldata(leverage_zap.address, MAX_UINT256),
            controller.approve.prepare_calldata(leverage_zap.address, True),
        ],
    )
    return batcher


def test_two_deposits_in_one_transaction(
    batcher,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    second_router,
    controller_id,
    price_oracle,
):
    """
    `create_loan` then `borrow_more`, one transaction, different exchange and a much
    smaller swap the second time. Both must use their own stashed parameters: the
    second swap's output is well below the first call's `min_recv`, so a stash that
    survived `_unstash` would either revert on slippage or move the wrong amount.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    price = price_oracle.price()

    user_collateral = 2 * 10**cd
    d_debt_1 = 3000 * 10**bd
    out_1 = collateral_from_borrowed(d_debt_1, price, bd, cd)
    min_recv_1, exchange_1, exchange_calldata_1 = make_deposit_calldata(
        controller_id,
        out_1 * 999 // 1000,
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt_1,
        out_1,
    )

    d_debt_2 = 300 * 10**bd
    out_2 = collateral_from_borrowed(d_debt_2, price, bd, cd)
    assert out_2 < min_recv_1  # a reused stash would fail the slippage check
    min_recv_2, exchange_2, exchange_calldata_2 = make_deposit_calldata(
        controller_id,
        out_2 * 999 // 1000,
        second_router,
        borrowed_token,
        collateral_token,
        d_debt_2,
        out_2,
    )
    assert exchange_1 != exchange_2

    batcher.execute(
        [leverage_zap.address, leverage_zap.address],
        [
            leverage_zap.create_loan.prepare_calldata(
                controller_id,
                user_collateral,
                d_debt_1,
                N,
                min_recv_1,
                exchange_1,
                exchange_calldata_1,
            ),
            leverage_zap.borrow_more.prepare_calldata(
                controller_id,
                0,
                d_debt_2,
                min_recv_2,
                exchange_2,
                exchange_calldata_2,
            ),
        ],
    )

    state = controller.user_state(batcher.address)
    assert state[0] == user_collateral + out_1 + out_2
    assert state[2] == d_debt_1 + d_debt_2
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


def test_deposit_then_repay_in_one_transaction(
    batcher,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    second_router,
    controller_id,
    price_oracle,
):
    """
    The two callbacks stash different things - `callback_deposit` measures its output in
    collateral and `callback_repay` in the borrowed token, and `stashed_held` is taken
    from the opposite token in each. Running a deposit and a repay back to back in one
    transaction is what would surface a field carried over between them.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    price = price_oracle.price()

    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    deposit_out = collateral_from_borrowed(d_debt, price, bd, cd)
    deposit_args = make_deposit_calldata(
        controller_id,
        deposit_out * 999 // 1000,
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        deposit_out,
    )

    # Sell a quarter of what the position will hold, through the other exchange
    collateral_to_swap = (user_collateral + deposit_out) // 4
    repay_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)
    repay_args = make_repay_calldata(
        controller_id,
        repay_out * 999 // 1000,
        second_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        repay_out,
    )

    batcher.execute(
        [leverage_zap.address, leverage_zap.address],
        [
            leverage_zap.create_loan.prepare_calldata(
                controller_id, user_collateral, d_debt, N, *deposit_args
            ),
            leverage_zap.repay.prepare_calldata(
                controller_id, 0, *repay_args, 2**255 - 1, False
            ),
        ],
    )

    state = controller.user_state(batcher.address)
    assert state[0] == user_collateral + deposit_out - collateral_to_swap
    assert state[2] == d_debt - repay_out
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


def test_stash_is_clear_after_a_reverted_call(
    batcher,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    second_router,
    controller_id,
    price_oracle,
):
    """
    A failed zap call whose revert is swallowed by the caller must not poison the rest
    of the transaction. `_unstash` never runs on that path - the stash is cleaned up by
    the revert rolling back transient storage - so this pins the behaviour the
    contract's "Transient storage is wiped at the end of the transaction anyway" comment
    leaves open for the middle of a transaction.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    price = price_oracle.price()

    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    out = collateral_from_borrowed(d_debt, price, bd, cd)

    # First call asks for more than the exchange will hand over
    doomed = make_deposit_calldata(
        controller_id,
        out + 1,
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        out,
    )
    good = make_deposit_calldata(
        controller_id,
        out * 999 // 1000,
        second_router,
        borrowed_token,
        collateral_token,
        d_debt,
        out,
    )

    batcher.execute(
        [leverage_zap.address, leverage_zap.address],
        [
            leverage_zap.create_loan.prepare_calldata(
                controller_id, user_collateral, d_debt, N, *doomed
            ),
            leverage_zap.create_loan.prepare_calldata(
                controller_id, user_collateral, d_debt, N, *good
            ),
        ],
        True,  # swallow the first revert and keep going
    )

    assert batcher.last_success(0) is False
    assert batcher.last_success(1) is True

    # The surviving call built the whole position by itself
    state = controller.user_state(batcher.address)
    assert state[0] == user_collateral + out
    assert state[2] == d_debt
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
