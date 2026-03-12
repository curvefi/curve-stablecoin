"""
E2E tests for LeverageZap.callback_deposit via controller.borrow_more.
"""

import boa
import pytest

from tests.utils.constants import MAX_UINT256, WAD
from tests.utils import filter_logs
from eth_abi import encode

from tests.e2e.zaps.leverage_zap.conftest import (
    collateral_from_borrowed,
    make_deposit_calldata,
)

N = 10


def test_borrow_more_d_debt(
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
    d_debt only: no user_collateral, no user_borrowed.
    All additional collateral comes from swapping d_debt.
    Checks state, Deposit event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)

    d_debt = 1000 * 10**bd
    price = price_oracle.price()
    collateral_out = collateral_from_borrowed(d_debt, price, bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
        0,
        collateral_out * 999 // 1000,
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        collateral_out,
    )

    with boa.env.prank(borrower):
        controller.borrow_more(0, d_debt, borrower, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Deposit", computation=controller._computation)

    # Check user's state
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] + collateral_out
    assert state1[2] == state0[2] + d_debt

    # Check event
    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.user_collateral == 0
    assert log.user_borrowed == 0
    assert log.debt == d_debt
    assert (
        log.leverage_collateral == collateral_out
    )  # all collateral attributed to d_debt
    assert log.user_collateral_from_borrowed == 0

    # The zap holds no tokens
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_borrow_more_d_debt_and_user_collateral(
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
    d_debt + user_collateral: user deposits extra collateral from wallet directly.
    No user_borrowed; all leveraged collateral comes from swapping d_debt.
    Checks state, Deposit event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)

    user_collateral = 1 * 10**cd
    d_debt = 1000 * 10**bd
    price = price_oracle.price()
    collateral_out = collateral_from_borrowed(d_debt, price, bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
        0,
        collateral_out * 999 // 1000,
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        collateral_out,
    )

    with boa.env.prank(borrower):
        controller.borrow_more(
            user_collateral, d_debt, borrower, leverage_zap.address, calldata
        )
    logs = filter_logs(leverage_zap, "Deposit", computation=controller._computation)

    # Check user's state
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] + user_collateral + collateral_out
    assert state1[2] == state0[2] + d_debt

    # Check event
    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.user_collateral == user_collateral
    assert log.user_borrowed == 0
    assert log.debt == d_debt
    assert (
        log.leverage_collateral == collateral_out
    )  # all collateral attributed to d_debt
    assert log.user_collateral_from_borrowed == 0

    # The zap holds no tokens
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_borrow_more_d_debt_and_user_borrowed(
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
    d_debt + user_borrowed: no direct collateral from wallet.
    The zap swaps (d_debt + user_borrowed) for additional collateral.
    Checks state, Deposit event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)

    user_borrowed = 300 * 10**bd
    d_debt = 1000 * 10**bd

    total_borrowed_in = d_debt + user_borrowed
    price = price_oracle.price()
    collateral_out = collateral_from_borrowed(total_borrowed_in, price, bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
        user_borrowed,
        collateral_out * 999 // 1000,
        dummy_router,
        borrowed_token,
        collateral_token,
        total_borrowed_in,
        collateral_out,
    )

    with boa.env.prank(borrower):
        controller.borrow_more(0, d_debt, borrower, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Deposit", computation=controller._computation)

    # Check user's state
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] + collateral_out
    assert state1[2] == state0[2] + d_debt

    # Check event
    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.user_collateral == 0
    assert log.user_borrowed == user_borrowed
    assert log.debt == d_debt
    expected_leverage = d_debt * WAD // total_borrowed_in * collateral_out // WAD
    assert log.leverage_collateral == expected_leverage
    assert log.user_collateral_from_borrowed == collateral_out - expected_leverage

    # The zap holds no tokens
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_borrow_more_leverage(
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
    Full happy path: d_debt + user_collateral + user_borrowed.
    The zap swaps (user_borrowed + d_debt) for additional leveraged collateral.
    Checks state, Deposit event fields, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)

    user_collateral = 1 * 10**cd
    user_borrowed = 300 * 10**bd
    d_debt = 1000 * 10**bd

    total_borrowed_in = d_debt + user_borrowed
    price = price_oracle.price()
    collateral_out = collateral_from_borrowed(total_borrowed_in, price, bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
        user_borrowed,
        collateral_out * 999 // 1000,
        dummy_router,
        borrowed_token,
        collateral_token,
        total_borrowed_in,
        collateral_out,
    )

    with boa.env.prank(borrower):
        controller.borrow_more(
            user_collateral, d_debt, borrower, leverage_zap.address, calldata
        )
    logs = filter_logs(leverage_zap, "Deposit", computation=controller._computation)

    # Check user's state
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] + user_collateral + collateral_out
    assert state1[2] == state0[2] + d_debt

    # Check event
    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.user_collateral == user_collateral
    assert log.user_borrowed == user_borrowed
    assert log.debt == d_debt
    expected_leverage = d_debt * WAD // total_borrowed_in * collateral_out // WAD
    assert log.leverage_collateral == expected_leverage
    assert log.user_collateral_from_borrowed == collateral_out - expected_leverage

    # The zap holds no tokens
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_borrow_more_slippage_reverts(
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

    d_debt = 1000 * 10**bd
    price = price_oracle.price()
    collateral_out = collateral_from_borrowed(d_debt, price, bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
        0,
        collateral_out + 1,  # min_recv 1 above actual
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        collateral_out,
    )

    with boa.env.prank(borrower):
        with boa.reverts("Slippage"):
            controller.borrow_more(0, d_debt, borrower, leverage_zap.address, calldata)


def test_callback_deposit_wrong_controller_reverts(
    leverage_zap,
    controller_id,
    dummy_router,
    borrowed_token,
    collateral_token,
):
    """Calling callback_deposit directly (not from controller) must revert."""
    attacker = boa.env.generate_address()

    exchange_data = dummy_router.exchange.prepare_calldata(
        borrowed_token.address, collateral_token.address, 0, 0
    )
    calldata = encode(
        ["uint256", "uint256", "uint256", "address", "bytes"],
        [controller_id, 0, 0, dummy_router.address, exchange_data],
    )

    with boa.env.prank(attacker):
        with boa.reverts("wrong controller"):
            leverage_zap.callback_deposit(attacker, 0, 0, 0, calldata)
