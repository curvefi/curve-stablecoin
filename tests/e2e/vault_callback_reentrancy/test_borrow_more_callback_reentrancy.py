"""
Vault callback reentrancy tests – borrow_more
=============================================
During borrow_more with a callbacker the controller's nonreentrant lock is held.
Vault.deposit/mint/withdraw/redeem all call controller.save_rate(), which is
not @reentrant, so any attempt to call those methods from within the callback
must revert.

pricePerShare/convertToAssets/convertToShares are unchanged at callback time:
available_balance drops by extra_debt while total_debt rises by extra_debt,
keeping totalAssets net-neutral both during and after the call.

Two collateral source scenarios are tested:
  wallet_and_callback – caller provides collateral from their wallet; callback
                        is invoked for any side effects only.
  callback_only       – all collateral is provided exclusively by the callback
                        via the collateral_to_deposit mechanism.

Each scenario is parametrized over different_caller to cover both self-call
and third-party-with-approval cases.
"""

import boa
import pytest

from tests.utils import max_approve
from tests.utils.constants import WAD

from tests.e2e.vault_callback_reentrancy.conftest import (
    N,
    ACTION_WITHDRAW,
    ACTION_REDEEM,
    ACTION_RECORD,
    VAULT_OPS,
    snapshot,
    assert_stable,
    open_max_loan,
    seed_shares,
    setup_caller,
)


# ---------------------------------------------------------------------------
# wallet + callback: caller provides wallet collateral
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("different_caller", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_borrow_more_wallet_and_callback(
    action,
    different_caller,
    controller,
    collateral_token,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Attempting vault.deposit/mint/withdraw/redeem inside a borrow_more callback
    must revert because save_rate() cannot be entered while the outer
    borrow_more call holds the reentrancy lock.

    Wallet provides the extra collateral; callback is invoked for side effects.
    Tested with both same-address and third-party caller.
    """
    cb.set_action(action)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    extra_debt = seed_liquidity // 20
    extra_collateral = controller.min_collateral(extra_debt, N) * 2
    boa.deal(collateral_token, cb.address, extra_collateral)
    cb.set_collateral_to_deposit(extra_collateral)
    caller = setup_caller(controller, borrower, different_caller)
    boa.deal(collateral_token, caller, extra_collateral)

    with boa.env.prank(caller):
        max_approve(collateral_token, controller)
        with boa.reverts("reentrant"):
            controller.borrow_more(
                extra_collateral, extra_debt, borrower, cb.address, b""
            )


@pytest.mark.parametrize("different_caller", [True, False])
def test_pps_stable_during_borrow_more_wallet_and_callback(
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
    during, and after borrow_more.

    Wallet provides the extra collateral.
    Tested with both same-address and third-party caller.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    extra_debt = seed_liquidity // 20
    extra_collateral = controller.min_collateral(extra_debt, N) * 2
    boa.deal(collateral_token, cb.address, extra_collateral)
    cb.set_collateral_to_deposit(extra_collateral)
    caller = setup_caller(controller, borrower, different_caller)
    boa.deal(collateral_token, caller, extra_collateral)

    before = snapshot(vault)

    with boa.env.prank(caller):
        max_approve(collateral_token, controller)
        controller.borrow_more(extra_collateral, extra_debt * 2, borrower, cb.address, b"")

    after = snapshot(vault)

    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# callback_only: callback provides all collateral via collateral_to_deposit
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("different_caller", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_borrow_more_callback_only(
    action,
    different_caller,
    controller,
    collateral_token,
    amm,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    Attempting vault.deposit/mint/withdraw/redeem inside a borrow_more callback
    must revert because save_rate() cannot be entered while the outer
    borrow_more call holds the reentrancy lock.

    All extra collateral is provided exclusively by the callback (wallet = 0).
    Tested with both same-address and third-party caller.
    """
    cb.set_action(action)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    extra_debt = seed_liquidity // 20
    extra_collateral = controller.min_collateral(extra_debt, N) * 2
    boa.deal(collateral_token, cb.address, extra_collateral)
    cb.set_collateral_to_deposit(extra_collateral)

    caller = setup_caller(controller, borrower, different_caller)

    with boa.env.prank(caller):
        with boa.reverts("reentrant"):
            controller.borrow_more(0, extra_debt, borrower, cb.address, b"")


@pytest.mark.parametrize("different_caller", [True, False])
def test_pps_stable_during_borrow_more_callback_only(
    different_caller,
    controller,
    collateral_token,
    amm,
    vault,
    borrowed_token,
    cb,
    seed_liquidity,
):
    """
    pricePerShare/convertToAssets/convertToShares must be identical before,
    during, and after borrow_more.

    All extra collateral is provided exclusively by the callback (wallet = 0).
    Tested with both same-address and third-party caller.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)

    extra_debt = seed_liquidity // 20
    extra_collateral = controller.min_collateral(extra_debt, N) * 2
    boa.deal(collateral_token, cb.address, extra_collateral)
    cb.set_collateral_to_deposit(extra_collateral)

    caller = setup_caller(controller, borrower, different_caller)

    before = snapshot(vault)

    with boa.env.prank(caller):
        controller.borrow_more(0, extra_debt, borrower, cb.address, b"")

    after = snapshot(vault)

    assert_stable(before, cb, after)
