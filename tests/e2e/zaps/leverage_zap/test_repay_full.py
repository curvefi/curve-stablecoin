"""
E2E tests for LeverageZap.callback_repay via controller.repay — full repayment (position close).
"""

import boa
import pytest

from tests.utils.constants import MAX_UINT256, WAD
from tests.utils import filter_logs

from tests.e2e.zaps.leverage_zap.conftest import (
    collateral_from_borrowed,
    borrowed_from_collateral,
    make_deposit_calldata,
    make_repay_calldata,
)

N = 10


def test_repay_full_state_collateral(
    open_position, controller, collateral_token, borrowed_token,
    leverage_zap, dummy_router, controller_id, price_oracle,
):
    """
    Swap all state collateral (worth ~3x the debt) to fully close the position.
    Checks position is closed, Repay event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0]
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)

    calldata = make_repay_calldata(
        controller_id, 0, 0, borrowed_out * 999 // 1000,
        dummy_router, collateral_token, borrowed_token,
        collateral_to_swap, borrowed_out,
    )

    with boa.env.prank(borrower):
        controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    assert not controller.loan_exists(borrower)

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


def test_repay_full_state_collateral_and_user_collateral(
    open_position, controller, collateral_token, borrowed_token,
    leverage_zap, dummy_router, controller_id, price_oracle,
):
    """
    Swap state collateral + user_collateral from wallet to fully close the position.
    Checks position is closed, Repay event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    extra_collateral = 10**cd // 5
    total_collateral_in = state0[0] + extra_collateral
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(total_collateral_in, price, bd, cd)

    calldata = make_repay_calldata(
        controller_id, extra_collateral, 0, borrowed_out * 999 // 1000,
        dummy_router, collateral_token, borrowed_token,
        total_collateral_in, borrowed_out,
    )

    with boa.env.prank(borrower):
        controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    assert not controller.loan_exists(borrower)

    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.state_collateral_used == state0[0]
    assert log.user_collateral == extra_collateral
    assert log.user_collateral_used == extra_collateral
    expected_bfs = state0[0] * WAD // total_collateral_in * borrowed_out // WAD
    assert log.borrowed_from_state_collateral == expected_bfs
    assert log.borrowed_from_user_collateral == borrowed_out - expected_bfs
    assert log.user_borrowed == 0

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_repay_full_state_collateral_and_user_borrowed(
    open_position, controller, collateral_token, borrowed_token,
    leverage_zap, dummy_router, controller_id, price_oracle,
):
    """
    Swap state collateral + user_borrowed from wallet to fully close the position.
    Checks position is closed, Repay event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0]
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)
    user_borrowed = 200 * 10**bd

    calldata = make_repay_calldata(
        controller_id, 0, user_borrowed, borrowed_out * 999 // 1000,
        dummy_router, collateral_token, borrowed_token,
        collateral_to_swap, borrowed_out,
    )

    with boa.env.prank(borrower):
        controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    assert not controller.loan_exists(borrower)

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


def test_repay_full_user_collateral_and_user_borrowed(
    open_position, controller, collateral_token, borrowed_token,
    leverage_zap, dummy_router, controller_id, price_oracle,
):
    """
    user_collateral (enough to cover the debt) + user_borrowed, no state collateral used.
    Excess user collateral is returned to the user via the controller after position closes.
    Checks position is closed, Repay event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    # Provide enough user_collateral to swap for more than the full debt
    extra_collateral = state0[0] * 2
    collateral_to_swap = state0[0]  # swap exactly state_collateral worth → closes position
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)
    user_borrowed = 200 * 10**bd

    calldata = make_repay_calldata(
        controller_id, extra_collateral, user_borrowed, borrowed_out * 999 // 1000,
        dummy_router, collateral_token, borrowed_token,
        collateral_to_swap, borrowed_out,
    )

    with boa.env.prank(borrower):
        controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    assert not controller.loan_exists(borrower)

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


def test_repay_full_leverage(
    open_position, controller, collateral_token, borrowed_token,
    leverage_zap, dummy_router, controller_id, price_oracle,
):
    """
    Full path with full repayment: state_collateral + user_collateral + user_borrowed.
    Checks position is closed, Repay event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    extra_collateral = 10**cd // 5
    total_collateral_in = state0[0] + extra_collateral
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(total_collateral_in, price, bd, cd)
    user_borrowed = 200 * 10**bd

    calldata = make_repay_calldata(
        controller_id, extra_collateral, user_borrowed, borrowed_out * 999 // 1000,
        dummy_router, collateral_token, borrowed_token,
        total_collateral_in, borrowed_out,
    )

    with boa.env.prank(borrower):
        controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    assert not controller.loan_exists(borrower)

    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.state_collateral_used == state0[0]
    assert log.user_collateral == extra_collateral
    assert log.user_collateral_used == extra_collateral
    expected_bfs = state0[0] * WAD // total_collateral_in * borrowed_out // WAD
    assert log.borrowed_from_state_collateral == expected_bfs
    assert log.borrowed_from_user_collateral == borrowed_out - expected_bfs
    assert log.user_borrowed == user_borrowed

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0
