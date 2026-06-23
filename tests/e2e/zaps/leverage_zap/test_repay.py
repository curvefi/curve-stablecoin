"""
E2E tests for LeverageZap.callback_repay via controller.repay.

The zap only swaps the position's state collateral (sent to it by the controller) into
the borrowed token. Wallet repayment is handled by the controller via its `_wallet_d_debt`
argument; the zap's `user_borrowed` is only an event annotation.
"""

import boa
from eth_abi import encode

from tests.utils import filter_logs
from tests.utils.deployers import DUMMY_ROUTER_DEPLOYER

from tests.e2e.zaps.leverage_zap.conftest import (
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
        0,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    assert controller.loan_exists(borrower)
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] - collateral_to_swap
    assert state1[2] == state0[2] - borrowed_out

    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.state_collateral_used == collateral_to_swap
    assert log.borrowed_from_state_collateral == borrowed_out
    assert log.user_borrowed == 0

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


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
    `user_borrowed` is passed in the calldata only for the event annotation.
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
        user_borrowed,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        controller.repay(
            user_borrowed, borrower, 2**255 - 1, leverage_zap.address, calldata
        )
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    assert controller.loan_exists(borrower)
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] - collateral_to_swap
    assert state1[2] == state0[2] - borrowed_out - user_borrowed

    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.state_collateral_used == collateral_to_swap
    assert log.borrowed_from_state_collateral == borrowed_out
    assert log.user_borrowed == user_borrowed

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


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
        0,
        borrowed_out + 1,  # min_recv 1 above actual
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        with boa.reverts("Slippage"):
            controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)


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
        0,
        borrowed_out * 999 // 1000,
        rogue_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        with boa.reverts("Exchange not approved"):
            controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)


def test_repay_wrong_controller_reverts(
    leverage_zap,
    controller_id,
    dummy_router,
    collateral_token,
    borrowed_token,
):
    """Calling callback_repay directly (not from controller) must revert."""
    attacker = boa.env.generate_address()

    exchange_data = dummy_router.exchange.prepare_calldata(
        collateral_token.address, borrowed_token.address, 0, 0
    )
    calldata = encode(
        ["uint256", "uint256", "uint256", "address", "bytes"],
        [controller_id, 0, 0, dummy_router.address, exchange_data],
    )

    with boa.env.prank(attacker):
        with boa.reverts("wrong controller"):
            leverage_zap.callback_repay(attacker, 0, 0, 0, calldata)
