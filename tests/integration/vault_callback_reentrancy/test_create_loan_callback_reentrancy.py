"""
Vault callback reentrancy tests – create_loan
=============================================
During a controller callback (create_loan with a callbacker) the controller's
nonreentrant lock is held.  All of Vault.deposit / mint / withdraw / redeem
eventually call controller.save_rate(), which is *not* @reentrant, so any
attempt to call those methods from within a callback must revert.

Separately, pricePerShare / convertToAssets / convertToShares are pure views.
Their inputs (totalAssets, totalSupply) are unchanged at callback time because
no vault state has been written yet, so the values must match those sampled
before the create_loan call.

Tests are parametrized over different_caller to verify that the reentrancy
protection and PPS stability also hold when a third party creates the loan
on behalf of the borrower (after receiving controller.approve).
"""

import boa
import pytest

from tests.utils import max_approve
from tests.utils.constants import WAD

from tests.integration.vault_callback_reentrancy.conftest import (
    N,
    ACTION_WITHDRAW,
    ACTION_REDEEM,
    ACTION_RECORD,
    VAULT_OPS,
    snapshot,
    assert_stable,
    seed_shares,
    setup_caller,
)


# ---------------------------------------------------------------------------
# Reentrancy tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("different_caller", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_callback(
    action,
    different_caller,
    controller,
    collateral_token,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Attempting vault.deposit/mint/withdraw/redeem from inside a controller
    callback must revert because controller.save_rate() cannot be entered
    while the outer create_loan call holds the reentrancy lock.

    Tested with both same-address and third-party creator.
    """
    cb.set_action(action)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    borrower = boa.env.generate_address()
    caller = setup_caller(controller, borrower, different_caller)

    debt = seed_liquidity // 10
    collateral = controller.min_collateral(debt, N)
    boa.deal(collateral_token, caller, collateral)
    with boa.env.prank(caller):
        max_approve(collateral_token, controller)
        with boa.reverts("reentrant"):
            controller.create_loan(
                collateral,
                debt,
                N,
                borrower,
                cb.address,
                b"",
            )


# ---------------------------------------------------------------------------
# PPS stability tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("different_caller", [True, False])
def test_pps_stable_during_create_loan_callback(
    different_caller,
    controller,
    collateral_token,
    vault,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    pricePerShare/convertToAssets/convertToShares must be identical before,
    during, and after create_loan.

    totalAssets = available_balance + total_debt - admin_fees.
    At callback time neither value has been updated yet, so totalAssets is
    unchanged and PPS must be stable.  After create_loan available_balance
    drops by debt while total_debt rises by debt, keeping totalAssets
    net-neutral.

    Tested with both same-address and third-party creator.
    """
    cb.set_action(ACTION_RECORD)

    borrower = boa.env.generate_address()
    caller = setup_caller(controller, borrower, different_caller)

    before = snapshot(vault)

    debt = seed_liquidity // 10
    collateral = controller.min_collateral(debt, N)
    boa.deal(collateral_token, caller, collateral)
    with boa.env.prank(caller):
        max_approve(collateral_token, controller)
        controller.create_loan(
            collateral,
            debt,
            N,
            borrower,
            cb.address,
            b"",
        )

    after = snapshot(vault)

    assert_stable(before, cb, after)
