"""
E2E tests for LeverageZap.callback_repay via controller.repay.
"""

import boa
import pytest

from tests.utils.constants import MAX_UINT256, WAD
from tests.utils import filter_logs
from eth_abi import encode

from tests.e2e.zaps.leverage_zap.conftest import (
    collateral_from_borrowed,
    borrowed_from_collateral,
    make_deposit_calldata,
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
    State collateral only: user provides no extras.
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
    assert log.user_collateral == 0
    assert log.user_collateral_used == 0
    assert log.borrowed_from_user_collateral == 0
    assert log.user_borrowed == 0

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_repay_state_collateral_and_user_collateral(
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
    State collateral + user_collateral: user adds extra collateral from wallet.
    Both are used in the swap; borrowed output is split proportionally.
    Checks state, Repay event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    state_portion = state0[0] // 5
    extra_collateral = 10**cd // 5
    total_collateral_in = state_portion + extra_collateral
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(total_collateral_in, price, bd, cd)

    calldata = make_repay_calldata(
        controller_id,
        extra_collateral,
        0,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        total_collateral_in,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    assert controller.loan_exists(borrower)
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] - state_portion
    assert state1[2] == state0[2] - borrowed_out

    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.state_collateral_used == state_portion
    assert log.user_collateral == extra_collateral
    assert log.user_collateral_used == extra_collateral
    expected_bfs = state_portion * WAD // total_collateral_in * borrowed_out // WAD
    assert log.borrowed_from_state_collateral == expected_bfs
    assert log.borrowed_from_user_collateral == borrowed_out - expected_bfs
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
    State collateral + user_borrowed: user swaps state collateral and also
    provides borrowed tokens from wallet for direct repayment.
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
        0,
        user_borrowed,
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
    assert state1[2] == state0[2] - borrowed_out - user_borrowed

    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.state_collateral_used == collateral_to_swap
    assert log.borrowed_from_state_collateral == borrowed_out
    assert log.user_collateral == 0
    assert log.user_collateral_used == 0
    assert log.borrowed_from_user_collateral == 0
    assert log.user_borrowed == user_borrowed

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_repay_user_collateral_and_user_borrowed(
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
    user_collateral + user_borrowed: user provides more collateral than the swap needs,
    so state collateral is untouched. User also provides borrowed tokens for direct repayment.
    Excess user collateral is returned to the position.
    Checks state, Repay event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    extra_collateral = 10**cd // 2
    collateral_to_swap = extra_collateral // 2  # only half used in swap
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)
    user_borrowed = 200 * 10**bd

    calldata = make_repay_calldata(
        controller_id,
        extra_collateral,
        user_borrowed,
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
    # excess user collateral (extra_collateral - collateral_to_swap) flows back into position
    assert state1[0] == state0[0] + extra_collateral - collateral_to_swap
    assert state1[2] == state0[2] - borrowed_out - user_borrowed

    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.state_collateral_used == 0
    assert log.borrowed_from_state_collateral == 0
    assert log.user_collateral == extra_collateral
    assert log.user_collateral_used == collateral_to_swap
    assert log.borrowed_from_user_collateral == borrowed_out
    assert log.user_borrowed == user_borrowed

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_repay_leverage(
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
    Full path: state_collateral + user_collateral + user_borrowed.
    Borrowed output is split proportionally between state and user collateral.
    Checks state, Repay event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    state_portion = state0[0] // 5
    extra_collateral = 10**cd // 10
    total_collateral_in = state_portion + extra_collateral
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(total_collateral_in, price, bd, cd)
    user_borrowed = 200 * 10**bd

    calldata = make_repay_calldata(
        controller_id,
        extra_collateral,
        user_borrowed,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        total_collateral_in,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    assert controller.loan_exists(borrower)
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] - state_portion
    assert state1[2] == state0[2] - borrowed_out - user_borrowed

    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.state_collateral_used == state_portion
    assert log.user_collateral == extra_collateral
    assert log.user_collateral_used == extra_collateral
    expected_bfs = state_portion * WAD // total_collateral_in * borrowed_out // WAD
    assert log.borrowed_from_state_collateral == expected_bfs
    assert log.borrowed_from_user_collateral == borrowed_out - expected_bfs
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


def test_callback_repay_wrong_controller_reverts(
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
        ["uint256", "uint256", "uint256", "uint256", "address", "bytes"],
        [controller_id, 0, 0, 0, dummy_router.address, exchange_data],
    )

    with boa.env.prank(attacker):
        with boa.reverts("wrong controller"):
            leverage_zap.callback_repay(attacker, 0, 0, 0, calldata)
