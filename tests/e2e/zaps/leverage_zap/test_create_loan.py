"""
E2E tests for LeverageZap.callback_deposit via controller.create_loan.
"""

import boa
import pytest

from tests.utils.constants import MAX_UINT256
from tests.utils import filter_logs
from tests.utils.deployers import DUMMY_ROUTER_DEPLOYER

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
    User deposits collateral directly and the zap swaps the borrowed d_debt for additional (leveraged) collateral.
    Checks state, Deposit event fields, and zero zap balances after.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd

    price = price_oracle.price()
    collateral_out = collateral_from_borrowed(d_debt, price, bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
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
    assert log.controller == controller.address
    assert log.user == borrower
    assert log.leverage_collateral == collateral_out
    assert log.d_debt == d_debt

    # The zap holds no tokens
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0

    # The exchange retains no allowance after the swap
    assert borrowed_token.allowance(leverage_zap.address, dummy_router.address) == 0


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


def test_create_loan_unapproved_exchange_reverts(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    controller_id,
    price_oracle,
):
    """A callback targeting an exchange that is not whitelisted reverts."""
    rogue_router = DUMMY_ROUTER_DEPLOYER.deploy()
    assert leverage_zap.is_approved_exchange(rogue_router.address) is False

    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    price = price_oracle.price()
    collateral_out = collateral_from_borrowed(d_debt, price, bd, cd)

    calldata = make_deposit_calldata(
        controller_id,
        collateral_out * 999 // 1000,
        rogue_router,
        borrowed_token,
        collateral_token,
        d_debt,
        collateral_out,
    )

    with boa.env.prank(borrower):
        with boa.reverts("Exchange not approved"):
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

    calldata = make_deposit_calldata(
        controller_id, 0, dummy_router, borrowed_token, collateral_token, 0, 0
    )

    with boa.env.prank(attacker):
        with boa.reverts("wrong controller"):
            leverage_zap.callback_deposit(attacker, 0, 0, 0, calldata)
