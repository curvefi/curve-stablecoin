"""
E2E tests for the dust / residual-balance handling fixed in the LeverageZap:

- Deposit: borrowed tokens the exchange does not spend are refunded to the user
  (instead of being stranded), and pre-existing collateral dust is flushed to the
  user instead of being counted as swap output.
- Repay: pre-existing borrowed dust is flushed to the user instead of being counted
  as swap output.
- In both callbacks the slippage check is enforced on the *swap output only*, so a
  pre-seeded / donated balance cannot satisfy `min_recv`.
- The zap holds zero of both tokens after every callback.
"""

import boa
import pytest

from tests.utils.constants import MAX_UINT256
from tests.utils import filter_logs

from tests.e2e.zaps.leverage_zap.conftest import (
    collateral_from_borrowed,
    borrowed_from_collateral,
    make_deposit_calldata,
    make_repay_calldata,
)

N = 10


@pytest.fixture
def borrower(controller, collateral_token, borrowed_token, leverage_zap):
    user = boa.env.generate_address()
    boa.deal(collateral_token, user, 10**6 * 10 ** collateral_token.decimals())
    boa.deal(borrowed_token, user, 10**6 * 10 ** borrowed_token.decimals())
    with boa.env.prank(user):
        collateral_token.approve(controller.address, MAX_UINT256)
        borrowed_token.approve(controller.address, MAX_UINT256)
    return user


# ---------------------------------------------------------------------------
# Deposit
# ---------------------------------------------------------------------------


def test_deposit_unspent_borrowed_refunded_to_user(
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
    The exchange spends only part of d_debt; the unspent borrowed must be refunded
    to the user rather than stranded in the zap.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    leftover = 500 * 10**bd  # borrowed the exchange will NOT spend
    borrowed_in = d_debt - leftover

    price = price_oracle.price()
    # Collateral is sized for the full d_debt so the position stays healthy; the
    # router has plenty of funds and will hand it over for the smaller borrowed_in.
    collateral_out = collateral_from_borrowed(d_debt, price, bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
        collateral_out * 999 // 1000,
        dummy_router,
        borrowed_token,
        collateral_token,
        borrowed_in,
        collateral_out,
    )

    b_before = borrowed_token.balanceOf(borrower)

    with boa.env.prank(borrower):
        controller.create_loan(
            user_collateral, d_debt, N, borrower, leverage_zap.address, calldata
        )

    # Unspent borrowed went back to the user, not the zap
    assert borrowed_token.balanceOf(borrower) == b_before + leftover
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0

    # Position is exactly the swapped collateral + user collateral / full debt
    state = controller.user_state(borrower)
    assert state[0] == user_collateral + collateral_out
    assert state[2] == d_debt


def test_deposit_collateral_dust_flushed_to_user(
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
    Pre-existing collateral dust in the zap must be flushed to the user and must NOT
    be counted as leverage collateral (event / position) nor left stranded.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    dust = 5 * 10**cd

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

    # Seed the zap with collateral dust (e.g. a donation)
    boa.deal(collateral_token, leverage_zap.address, dust)
    c_before = collateral_token.balanceOf(borrower)

    with boa.env.prank(borrower):
        controller.create_loan(
            user_collateral, d_debt, N, borrower, leverage_zap.address, calldata
        )
    logs = filter_logs(leverage_zap, "Deposit", computation=controller._computation)

    # Dust returned to user; only the swap output counts as leverage collateral
    assert collateral_token.balanceOf(borrower) == c_before - user_collateral + dust
    assert logs[0].controller == controller.address
    assert logs[0].leverage_collateral == collateral_out

    state = controller.user_state(borrower)
    assert state[0] == user_collateral + collateral_out  # dust not added to position

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_deposit_donated_collateral_cannot_mask_slippage(
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
    Donated collateral dust must not be able to satisfy min_recv: with the dust
    flushed first, min_recv just above the swap output reverts with 'Slippage'.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    dust = 5 * 10**cd  # far more than the 1-wei min_recv margin below

    price = price_oracle.price()
    collateral_out = collateral_from_borrowed(d_debt, price, bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
        collateral_out + 1,  # 1 above the actual swap output
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        collateral_out,
    )

    boa.deal(collateral_token, leverage_zap.address, dust)

    with boa.env.prank(borrower):
        with boa.reverts("Slippage"):
            controller.create_loan(
                user_collateral, d_debt, N, borrower, leverage_zap.address, calldata
            )


# ---------------------------------------------------------------------------
# Repay
# ---------------------------------------------------------------------------


def test_repay_borrowed_dust_flushed_to_user(
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
    Pre-existing borrowed dust in the zap must be flushed to the user and must NOT
    be counted as borrowed_from_state_collateral (event) nor used to repay debt.
    The user's state collateral is NOT dust and must be used as usual.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)
    dust = 50 * 10**bd

    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    # Seed the zap with borrowed dust (e.g. a donation) and no wallet repayment
    boa.deal(borrowed_token, leverage_zap.address, dust)
    b_before = borrowed_token.balanceOf(borrower)

    with boa.env.prank(borrower):
        controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=controller._computation)

    # Dust returned to user; only the swap output repaid debt
    assert borrowed_token.balanceOf(borrower) == b_before + dust
    assert logs[0].controller == controller.address
    assert logs[0].borrowed_from_state_collateral == borrowed_out
    assert logs[0].state_collateral_used == collateral_to_swap

    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] - collateral_to_swap  # state collateral used as usual
    assert state1[2] == state0[2] - borrowed_out  # dust did not reduce debt

    assert borrowed_token.balanceOf(leverage_zap.address) == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0


def test_repay_donated_borrowed_cannot_mask_slippage(
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
    Donated borrowed dust must not be able to satisfy min_recv: with the dust
    flushed first, min_recv just above the swap output reverts with 'Slippage'.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    price = price_oracle.price()
    borrowed_out = borrowed_from_collateral(collateral_to_swap, price, bd, cd)
    dust = 50 * 10**bd  # far more than the 1-wei min_recv margin below

    calldata = make_repay_calldata(
        controller_id,
        borrowed_out + 1,  # 1 above the actual swap output
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    boa.deal(borrowed_token, leverage_zap.address, dust)

    with boa.env.prank(borrower):
        with boa.reverts("Slippage"):
            controller.repay(0, borrower, 2**255 - 1, leverage_zap.address, calldata)
