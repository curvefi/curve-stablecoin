"""
E2E tests for LeverageZap.callback_repay via controller.repay.

The zap only swaps the position's state collateral (sent to it by the controller) into
the borrowed token. Wallet repayment is handled by the controller via its `_wallet_d_debt`
argument.
"""

import boa

from tests.utils import filter_logs
from tests.utils.deployers import DUMMY_ROUTER_DEPLOYER

from tests.e2e.zaps.transient_leverage_zap.conftest import (
    borrowed_from_collateral,
    make_repay_calldata,
)

N = 10


def test_repay_state_collateral(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    State collateral only (no wallet repayment).
    Swap 1/4 of state collateral for borrowed to partially repay debt.
    Checks state, Repay event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    # State collateral is worth ~3x the debt, so swap only 1/4
    # to ensure borrowed_out < state_debt (partial repay).
    collateral_to_swap = state0[0] // 4
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)

    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        leverage_zap.repay(controller_id, 0, *calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=leverage_zap._computation)

    assert controller.loan_exists(borrower)
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] - collateral_to_swap
    assert state1[2] == state0[2] - borrowed_out

    assert len(logs) == 1
    log = logs[0]
    assert log.controller == controller.address
    assert log.user == borrower
    assert log.state_collateral_used == collateral_to_swap
    assert log.borrowed_from_state_collateral == borrowed_out

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0

    # The exchange retains no allowance after the swap
    assert collateral_token.allowance(leverage_zap.address, dummy_router.address) == 0


def test_repay_state_collateral_and_user_borrowed(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    State collateral swap + wallet repayment: the zap swaps state collateral while the
    user also repays from their wallet via the controller's `_wallet_d_debt`.
    Checks state, Repay event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)
    user_borrowed = 200 * 10**bd

    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        leverage_zap.repay(controller_id, user_borrowed, *calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=leverage_zap._computation)

    assert controller.loan_exists(borrower)
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] - collateral_to_swap
    assert state1[2] == state0[2] - borrowed_out - user_borrowed

    assert len(logs) == 1
    log = logs[0]
    assert log.controller == controller.address
    assert log.user == borrower
    assert log.state_collateral_used == collateral_to_swap
    assert log.borrowed_from_state_collateral == borrowed_out

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0

    # The exchange retains no allowance after the swap
    assert collateral_token.allowance(leverage_zap.address, dummy_router.address) == 0


def test_repay_slippage_reverts(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """min_recv set 1 above actual → reverts with 'Slippage'."""
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)

    calldata = make_repay_calldata(
        controller_id,
        borrowed_out + 1,  # min_recv 1 above actual
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        with boa.reverts("Slippage"):
            leverage_zap.repay(controller_id, 0, *calldata)


def test_repay_unapproved_exchange_reverts(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    controller_id,
    price_oracle,
):
    """A callback targeting an exchange that is not whitelisted reverts."""
    borrower = open_position()
    rogue_router = DUMMY_ROUTER_DEPLOYER.deploy()
    assert leverage_zap.is_approved_exchange(rogue_router.address) is False

    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)

    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        rogue_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        with boa.reverts("Exchange not approved"):
            leverage_zap.repay(controller_id, 0, *calldata)


def test_repay_wrong_controller_reverts(
    leverage_zap,
    controller_id,
    dummy_router,
    collateral_token,
    borrowed_token,
):
    """Calling callback_repay directly (not from controller) must revert."""
    attacker = boa.env.generate_address()

    with boa.env.prank(attacker):
        with boa.reverts("wrong controller"):
            leverage_zap.callback_repay(attacker, 0, 0, 0, b"")


def test_repay_exchange_cannot_take_more_than_collateral_to_spend(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    The zap holds the whole state collateral during the callback, but the exchange is only
    approved for `_collateral_to_spend`. A route selling more than that reverts.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    borrowed_out = borrowed_from_collateral(
        collateral_to_swap, price_oracle.price(), bd, cd
    )

    _, min_recv, exchange, exchange_calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        with boa.reverts("erc20: insufficient allowance"):
            leverage_zap.repay(
                controller_id,
                0,
                collateral_to_swap - 1,
                min_recv,
                exchange,
                exchange_calldata,
            )

    assert controller.user_state(borrower) == state0
    assert collateral_token.allowance(leverage_zap.address, dummy_router.address) == 0

    # Exactly the cap goes through, and no allowance is left behind
    with boa.env.prank(borrower):
        leverage_zap.repay(
            controller_id,
            0,
            collateral_to_swap,
            min_recv,
            exchange,
            exchange_calldata,
        )

    assert controller.user_state(borrower)[0] == state0[0] - collateral_to_swap
    assert collateral_token.allowance(leverage_zap.address, dummy_router.address) == 0
