"""
Vault callback reentrancy tests – repay
=======================================
During repay with a callbacker the controller's nonreentrant lock is held.
callback_repay receives the full collateral withdrawn from the AMM and must
return (borrowed_from_callback, collateral_destination).  Any vault operation
attempted from within the callback must revert.

For deposit/mint the controller sends only collateral to cb (not borrowed
tokens); cb is pre-funded with borrowed tokens so the vault call reaches
save_rate() rather than reverting at the ERC20 transfer.

pricePerShare/convertToAssets/convertToShares are unchanged at callback time:
at callback, no state writes have been committed; after repay, available_balance
rises by d_debt while total_debt falls by d_debt, keeping totalAssets net-neutral.

Scenarios tested (each with reentrancy + PPS stability):
  full_repay_from_wallet        – wallet covers full debt; cb handles collateral.
  full_repay_from_callback      – cb covers full debt; wallet = 0.
  full_repay_from_wallet_and_callback – wallet covers half, cb covers other half.
  full_repay_from_xy0_and_callback    – position underwater; xy[0] + cb cover debt.
  full_repay_from_xy0_wallet_and_callback – xy[0] + wallet + cb cover debt.
  partial_repay_from_callback         – cb covers partial debt; position stays open.
  partial_repay_from_wallet_and_callback – wallet + cb cover partial debt.
  partial_repay_from_xy0_and_callback_underwater_shrink – shrink mode.
  partial_repay_from_xy0_wallet_and_callback_underwater_shrink – shrink mode + wallet.

Each scenario is parametrized over different_payer (True/False).
"""

import boa
import pytest

from tests.utils import max_approve
from tests.utils.constants import MAX_UINT256, WAD

from tests.e2e.vault_callback_reentrancy.conftest import (
    N,
    ACTION_WITHDRAW,
    ACTION_REDEEM,
    ACTION_RECORD,
    VAULT_OPS,
    snapshot,
    assert_stable,
    open_max_loan,
    seed_borrowed,
    seed_shares,
    setup_caller,
)

_MAX_INT256 = 2**255 - 1
_N_SHRINK = 6  # bands needed for shrink tests (> MIN_TICKS so shrink is possible)


def _push_underwater(borrower, controller, amm, borrowed_token):
    """Exchange debt//2 of borrowed tokens for collateral to create xy[0] > 0."""
    trader = boa.env.generate_address("trader")
    debt = controller.debt(borrower)
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    assert (
        controller.user_state(borrower)[0] > 0
        and controller.user_state(borrower)[1] > 0
    )


def _open_shrinkable_loan(controller, collateral_token, amm, borrowed_token, debt):
    """Open a loan with _N_SHRINK bands and soft-liquidate one band so that
    shrink is possible (active band inside position bands, xy[0] > 0)."""
    borrower = open_max_loan(controller, collateral_token, debt, _N_SHRINK)
    ticks = amm.read_user_tick_numbers(borrower)
    amount_out = max(amm.bands_y(ticks[0]) // 100, 1)
    dx = amm.get_dx(0, 1, amount_out)
    trader = boa.env.generate_address()
    boa.deal(borrowed_token, trader, dx)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange_dy(0, 1, amount_out, dx + 1)

    assert (
        controller.user_state(borrower)[0] > 0
        and controller.user_state(borrower)[1] > 0
    )

    return borrower


# ---------------------------------------------------------------------------
# Full repay – callback (cb covers full debt; wallet = 0)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("different_payer", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_full_repay_from_callback(
    action,
    different_payer,
    controller,
    collateral_token,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during repay callback when the callback
    exclusively covers the full debt (wallet_d_debt = 0).
    """
    cb.set_action(action)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    boa.deal(borrowed_token, cb.address, debt)
    cb.set_borrowed_to_return(debt)

    payer = setup_caller(controller, borrower, different_payer)

    with boa.env.prank(payer):
        with boa.reverts("reentrant"):
            controller.repay(0, borrower, _MAX_INT256, cb.address, b"")


@pytest.mark.parametrize("different_payer", [True, False])
def test_pps_stable_during_full_repay_from_callback(
    different_payer,
    controller,
    collateral_token,
    vault,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after repay when the callback
    exclusively covers the full debt.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    boa.deal(borrowed_token, cb.address, debt)
    cb.set_borrowed_to_return(debt)

    payer = setup_caller(controller, borrower, different_payer)

    before = snapshot(vault)

    with boa.env.prank(payer):
        controller.repay(0, borrower, _MAX_INT256, cb.address, b"")

    after = snapshot(vault)

    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# Full repay – wallet + callback (both contribute to full debt)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("different_payer", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_full_repay_from_wallet_and_callback(
    action,
    different_payer,
    controller,
    collateral_token,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during repay callback when wallet and callback
    together cover the full debt.
    """
    cb.set_action(action)
    cb.set_borrowed_to_return(0)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    half_debt = debt // 2
    payer = setup_caller(controller, borrower, different_payer)
    boa.deal(borrowed_token, payer, half_debt)

    boa.deal(borrowed_token, cb.address, half_debt)
    cb.set_borrowed_to_return(half_debt)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        with boa.reverts("reentrant"):
            controller.repay(half_debt, borrower, _MAX_INT256, cb.address, b"")


@pytest.mark.parametrize("different_payer", [True, False])
def test_pps_stable_during_full_repay_from_wallet_and_callback(
    different_payer,
    controller,
    collateral_token,
    vault,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after repay when wallet and callback
    together cover the full debt.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    half_debt = debt // 2
    payer = setup_caller(controller, borrower, different_payer)
    boa.deal(borrowed_token, payer, half_debt)

    boa.deal(borrowed_token, cb.address, half_debt)
    cb.set_borrowed_to_return(half_debt)

    before = snapshot(vault)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        controller.repay(half_debt, borrower, _MAX_INT256, cb.address, b"")

    after = snapshot(vault)

    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# Full repay – xy[0] + callback (underwater position)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("different_payer", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_full_repay_from_xy0_and_callback(
    action,
    different_payer,
    controller,
    collateral_token,
    amm,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during repay callback when the position is
    underwater and xy[0] + callback together cover the full debt.
    """
    cb.set_action(action)
    cb.set_borrowed_to_return(0)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    _push_underwater(borrower, controller, amm, borrowed_token)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    xy0 = controller.user_state(borrower)[1]
    cb_portion = controller.debt(borrower) - xy0 + 1  # +1 for rounding
    boa.deal(borrowed_token, cb.address, cb_portion)
    cb.set_borrowed_to_return(cb_portion)

    payer = setup_caller(controller, borrower, different_payer)

    with boa.env.prank(payer):
        with boa.reverts("reentrant"):
            controller.repay(0, borrower, _MAX_INT256, cb.address, b"")


@pytest.mark.parametrize("different_payer", [True, False])
def test_pps_stable_during_full_repay_from_xy0_and_callback(
    different_payer,
    controller,
    collateral_token,
    amm,
    vault,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after repay when the position is
    underwater and xy[0] + callback together cover the full debt.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    _push_underwater(borrower, controller, amm, borrowed_token)

    xy0 = controller.user_state(borrower)[1]
    cb_portion = controller.debt(borrower) - xy0 + 1  # +1 for rounding
    boa.deal(borrowed_token, cb.address, cb_portion)
    cb.set_borrowed_to_return(cb_portion)

    payer = setup_caller(controller, borrower, different_payer)

    before = snapshot(vault)

    with boa.env.prank(payer):
        controller.repay(0, borrower, _MAX_INT256, cb.address, b"")

    after = snapshot(vault)

    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# Full repay – xy[0] + wallet + callback (underwater position)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("different_payer", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_full_repay_from_xy0_wallet_and_callback(
    action,
    different_payer,
    controller,
    collateral_token,
    amm,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during repay callback when the position is
    underwater and xy[0] + wallet + callback together cover the full debt.
    """
    cb.set_action(action)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    _push_underwater(borrower, controller, amm, borrowed_token)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    xy0 = controller.user_state(borrower)[1]
    remaining = controller.debt(borrower) - xy0
    wallet_portion = remaining // 2
    cb_portion = remaining - wallet_portion + 1  # +1 for rounding
    boa.deal(borrowed_token, cb.address, cb_portion)
    cb.set_borrowed_to_return(cb_portion)

    payer = setup_caller(controller, borrower, different_payer)
    boa.deal(borrowed_token, payer, wallet_portion)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        with boa.reverts("reentrant"):
            controller.repay(wallet_portion, borrower, _MAX_INT256, cb.address, b"")


@pytest.mark.parametrize("different_payer", [True, False])
def test_pps_stable_during_full_repay_from_xy0_wallet_and_callback(
    different_payer,
    controller,
    collateral_token,
    amm,
    vault,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after repay when the position is
    underwater and xy[0] + wallet + callback together cover the full debt.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    _push_underwater(borrower, controller, amm, borrowed_token)

    xy0 = controller.user_state(borrower)[1]
    remaining = controller.debt(borrower) - xy0
    wallet_portion = remaining // 2
    cb_portion = remaining - wallet_portion + 1  # +1 for rounding
    boa.deal(borrowed_token, cb.address, cb_portion)
    cb.set_borrowed_to_return(cb_portion)

    payer = setup_caller(controller, borrower, different_payer)
    boa.deal(borrowed_token, payer, wallet_portion)

    before = snapshot(vault)
    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        controller.repay(wallet_portion, borrower, _MAX_INT256, cb.address, b"")
    after = snapshot(vault)
    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# Partial repay – callback (cb covers partial debt; position stays open)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("different_payer", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_partial_repay_from_callback(
    action,
    different_payer,
    controller,
    collateral_token,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during repay callback when the callback
    covers only a partial portion of the debt (position remains open).
    """
    cb.set_action(action)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    partial = debt // 3
    boa.deal(borrowed_token, cb.address, partial)
    cb.set_borrowed_to_return(partial)

    payer = setup_caller(controller, borrower, different_payer)

    with boa.env.prank(payer):
        with boa.reverts("reentrant"):
            controller.repay(0, borrower, _MAX_INT256, cb.address, b"")


@pytest.mark.parametrize("different_payer", [True, False])
def test_pps_stable_during_partial_repay_from_callback(
    different_payer,
    controller,
    collateral_token,
    vault,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after a partial repay where the
    callback exclusively covers part of the debt.  Position stays open.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    partial = debt // 3
    boa.deal(borrowed_token, cb.address, partial)
    cb.set_borrowed_to_return(partial)

    payer = setup_caller(controller, borrower, different_payer)

    before = snapshot(vault)
    with boa.env.prank(payer):
        # wallet_d_debt=0 so only callback provides the partial repayment
        controller.repay(0, borrower, _MAX_INT256, cb.address, b"")
    after = snapshot(vault)
    assert controller.loan_exists(borrower)  # position still open
    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# Partial repay – wallet + callback (both cover partial debt)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("different_payer", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_partial_repay_from_wallet_and_callback(
    action,
    different_payer,
    controller,
    collateral_token,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during repay callback when wallet and callback
    together cover only a partial portion of the debt.
    """
    cb.set_action(action)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    wallet_portion = debt // 4
    cb_portion = debt // 4
    boa.deal(borrowed_token, cb.address, cb_portion)
    cb.set_borrowed_to_return(cb_portion)

    payer = setup_caller(controller, borrower, different_payer)
    boa.deal(borrowed_token, payer, wallet_portion)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        with boa.reverts("reentrant"):
            controller.repay(wallet_portion, borrower, _MAX_INT256, cb.address, b"")


@pytest.mark.parametrize("different_payer", [True, False])
def test_pps_stable_during_partial_repay_from_wallet_and_callback(
    different_payer,
    controller,
    collateral_token,
    vault,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after a partial repay where wallet
    and callback together cover part of the debt.  Position stays open.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    wallet_portion = debt // 4
    cb_portion = debt // 4
    boa.deal(borrowed_token, cb.address, cb_portion)
    cb.set_borrowed_to_return(cb_portion)

    payer = setup_caller(controller, borrower, different_payer)
    boa.deal(borrowed_token, payer, wallet_portion)

    before = snapshot(vault)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        controller.repay(wallet_portion, borrower, _MAX_INT256, cb.address, b"")
        assert controller.loan_exists(borrower)  # position still open

    after = snapshot(vault)

    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# Partial repay – xy[0] + callback (underwater, shrink)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("different_payer", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_partial_repay_from_xy0_and_callback_underwater_shrink(
    action,
    different_payer,
    controller,
    collateral_token,
    amm,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during a shrink repay callback when the position
    is partially underwater and xy[0] + callback cover some debt with shrink=True.
    """
    cb.set_action(action)

    debt = seed_liquidity // 10
    borrower = _open_shrinkable_loan(
        controller, collateral_token, amm, borrowed_token, debt
    )

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)
    else:
        seed_borrowed(cb, borrowed_token, WAD)

    payer = setup_caller(controller, borrower, different_payer)

    with boa.env.prank(payer):
        with boa.reverts("reentrant"):
            controller.repay(0, borrower, amm.active_band(), cb.address, b"", True)


@pytest.mark.parametrize("different_payer", [True, False])
def test_pps_stable_during_partial_repay_from_xy0_and_callback_underwater_shrink(
    different_payer,
    controller,
    collateral_token,
    amm,
    vault,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after a shrink repay where the
    position is partially underwater and xy[0] partially reduces debt.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = _open_shrinkable_loan(
        controller, collateral_token, amm, borrowed_token, debt
    )

    payer = setup_caller(controller, borrower, different_payer)

    before = snapshot(vault)

    with boa.env.prank(payer):
        # shrink=True: xy[0] automatically reduces debt; callback provides 0.
        controller.repay(0, borrower, amm.active_band(), cb.address, b"", True)
        assert controller.loan_exists(borrower)  # position still open after shrink

    after = snapshot(vault)

    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# Partial repay – xy[0] + wallet + callback (underwater, shrink)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("different_payer", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_partial_repay_from_xy0_wallet_and_callback_underwater_shrink(
    action,
    different_payer,
    controller,
    collateral_token,
    amm,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during a shrink repay callback when xy[0],
    wallet, and callback together cover some debt with shrink=True.
    """
    cb.set_action(action)

    debt = seed_liquidity // 10
    borrower = _open_shrinkable_loan(
        controller, collateral_token, amm, borrowed_token, debt
    )

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)
    else:
        seed_borrowed(cb, borrowed_token, WAD)

    payer = setup_caller(controller, borrower, different_payer)
    wallet_portion = controller.debt(borrower) // 8
    boa.deal(borrowed_token, payer, wallet_portion)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        with boa.reverts("reentrant"):
            controller.repay(
                wallet_portion, borrower, amm.active_band(), cb.address, b"", True
            )


@pytest.mark.parametrize("different_payer", [True, False])
def test_pps_stable_during_partial_repay_from_xy0_wallet_and_callback_underwater_shrink(
    different_payer,
    controller,
    collateral_token,
    amm,
    vault,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after a shrink repay where xy[0],
    wallet, and callback together partially reduce the debt.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = _open_shrinkable_loan(
        controller, collateral_token, amm, borrowed_token, debt
    )

    payer = setup_caller(controller, borrower, different_payer)
    wallet_portion = controller.debt(borrower) // 8
    boa.deal(borrowed_token, payer, wallet_portion)

    before = snapshot(vault)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        controller.repay(
            wallet_portion, borrower, amm.active_band(), cb.address, b"", True
        )
        assert controller.loan_exists(borrower)  # position still open after shrink

    after = snapshot(vault)

    assert_stable(before, cb, after)
