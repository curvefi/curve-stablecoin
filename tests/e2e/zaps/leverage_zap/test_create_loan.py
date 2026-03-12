"""
E2E tests for LeverageZap.callback_deposit via controller.create_loan.
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


@pytest.fixture
def borrower(controller, collateral_token, borrowed_token, leverage_zap):
    user = boa.env.generate_address()
    boa.deal(collateral_token, user, 10**6 * 10 ** collateral_token.decimals())
    boa.deal(borrowed_token, user, 10**6 * 10 ** borrowed_token.decimals())
    with boa.env.prank(user):
        collateral_token.approve(controller.address, MAX_UINT256)
        borrowed_token.approve(leverage_zap.address, MAX_UINT256)
    return user


def test_create_loan_leverage(
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
    Full happy path: user deposits collateral + some borrowed tokens from wallet.
    The zap swaps (user_borrowed + d_debt) for additional collateral.
    Checks state, Deposit event fields, and zero zap balances after.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    user_borrowed = 300 * 10**bd
    d_debt = 3000 * 10**bd

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
        controller.create_loan(
            user_collateral, d_debt, N, borrower, leverage_zap.address, calldata
        )
    logs = filter_logs(leverage_zap, "Deposit", computation=controller._computation)

    # Check user's state
    state = controller.user_state(borrower)
    assert state[0] == user_collateral + collateral_out
    assert state[2] == d_debt

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


def test_create_loan_only_collateral(
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
    user_borrowed == 0: all additional collateral comes from swapping d_debt only.
    Checks state, Deposit event (user_borrowed == 0), and zero zap balances after.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd

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
        controller.create_loan(
            user_collateral, d_debt, N, borrower, leverage_zap.address, calldata
        )
    logs = filter_logs(leverage_zap, "Deposit", computation=controller._computation)

    # Check user's state
    state = controller.user_state(borrower)
    assert state[0] == user_collateral + collateral_out
    assert state[2] == d_debt

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


def test_create_loan_slippage_reverts(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """min_recv set 1 above actual out → reverts with 'Slippage'."""
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
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
            controller.create_loan(
                user_collateral, d_debt, N, borrower, leverage_zap.address, calldata
            )


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
