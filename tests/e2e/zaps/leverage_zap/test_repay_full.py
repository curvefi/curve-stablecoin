"""
E2E tests for LeverageZap.callback_repay via controller.repay — full repayment (position close).

The zap only swaps the position's state collateral. Any shortfall needed to fully close the
loan is pulled from the user's wallet by the controller via its `_wallet_d_debt` argument.
"""

import boa

from tests.utils import filter_logs

from tests.e2e.zaps.leverage_zap.conftest import (
    borrowed_from_collateral,
    make_repay_calldata,
)

N = 10


def test_repay_full_state_collateral(
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
    Swap all state collateral (worth ~3x the debt) to fully close the position, no wallet
    repayment. Excess borrowed proceeds are returned to the user by the controller.
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
        controller_id,
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

    assert not controller.loan_exists(borrower)

    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.state_collateral_used == collateral_to_swap
    assert log.borrowed_from_state_collateral == borrowed_out

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_repay_full_state_collateral_and_user_borrowed(
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
    Swap part of the state collateral (not enough alone) and let the controller pull the
    remaining shortfall from the user's wallet via `_wallet_d_debt` to fully close the loan.
    The remaining (unswapped) state collateral is returned to the user.
    The actual wallet repayment is the shortfall computed by the controller.
    Checks position is closed, Repay event fields, wallet usage, and zero zap balances after.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    # Swap only 1/4 of state collateral → borrowed_out < debt, so the wallet must cover the rest.
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

    borrowed_before = borrowed_token.balanceOf(borrower)
    with boa.env.prank(borrower):
        # _wallet_d_debt huge → controller pulls the exact shortfall to fully repay.
        controller.repay(
            2**255 - 1, borrower, 2**255 - 1, leverage_zap.address, calldata
        )
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    assert not controller.loan_exists(borrower)
    # The wallet was used to cover the shortfall.
    assert borrowed_token.balanceOf(borrower) < borrowed_before

    assert len(logs) == 1
    log = logs[0]
    assert log.user == borrower
    assert log.state_collateral_used == collateral_to_swap
    assert log.borrowed_from_state_collateral == borrowed_out

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_repay_full_slippage_reverts(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """Full close: min_recv set 1 above actual → reverts with 'Slippage'."""
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0]
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
            controller.repay(
                2**255 - 1, borrower, 2**255 - 1, leverage_zap.address, calldata
            )
