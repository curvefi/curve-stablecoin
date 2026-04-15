"""
Vault callback reentrancy tests – liquidate
===========================================
During liquidate with a callbacker the controller's nonreentrant lock is held.
callback_liquidate receives the collateral withdrawn from the AMM and must
return at least (debt - xy[0]) borrowed tokens.  Any vault operation attempted
from within the callback must revert.

For deposit/mint the controller sends only collateral to cb (not borrowed
tokens); cb is pre-funded with borrowed tokens so the vault call reaches
save_rate() rather than reverting at the ERC20 transfer.

pricePerShare/convertToAssets/convertToShares are unchanged at callback time:
no state writes have been committed yet; after liquidate, available_balance
rises by the repaid debt while total_debt falls by the same amount.

Scenarios tested (each with reentrancy + PPS stability):
  full_from_callback              – position not underwater; cb covers full debt.
  full_from_callback_underwater   – position soft-liquidated; xy[0]+cb cover debt.
  partial_from_callback           – 50% liquidation; cb covers the partial debt.
  partial_from_callback_underwater – 50% liquidation of a soft-liquidated position.

Each scenario is parametrized over different_caller (True/False) and
is_healthy (True/False).  When is_healthy=True the position is not made
liquidatable and the caller self-liquidates (approval required for
different_caller=True).
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
    seed_borrowed,
    setup_caller,
)

_FRAC_HALF = WAD // 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_liquidator(controller, borrower, different_caller, is_healthy):
    if is_healthy:
        # Gives an approval to different caller
        return setup_caller(controller, borrower, different_caller)

    if different_caller:
        # A different caller without an approval
        return boa.env.generate_address()
    return borrower


def _make_liquidatable(controller, price_oracle, admin, borrower):
    """Drop oracle price by half so health < 0."""
    with boa.env.prank(admin):
        price_oracle.set_price(price_oracle.price() // 2)

    assert controller.health(borrower, True) < 0


def _push_underwater(borrower, controller, amm, borrowed_token):
    """Exchange debt//2 of borrowed tokens for collateral to create xy[0] > 0."""
    trader = boa.env.generate_address("trader")
    debt = controller.debt(borrower)
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    assert controller.user_state(borrower)[0] > 0 and controller.user_state(borrower)[1] > 0


# ---------------------------------------------------------------------------
# Full liquidation from callback (not underwater)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("is_healthy", [True, False])
@pytest.mark.parametrize("different_caller", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_liquidate_full_from_callback(
    action,
    different_caller,
    is_healthy,
    controller,
    price_oracle,
    admin,
    borrowed_token,
    collateral_token,
    cb,
    seed_liquidity,
):
    """
    Attempting vault.deposit/mint/withdraw/redeem inside a liquidate callback
    must revert because save_rate() cannot be entered while the outer liquidate
    call holds the reentrancy lock.

    Position is not underwater (xy[0] = 0); cb covers the full debt.
    """
    cb.set_action(action)
    cb.set_borrowed_to_return(0)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    if is_healthy:
        assert controller.health(borrower, True) > 0
    else:
        _make_liquidatable(controller, price_oracle, admin, borrower)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    boa.deal(borrowed_token, cb.address, debt)
    cb.set_borrowed_to_return(debt)

    caller = _setup_liquidator(controller, borrower, different_caller, is_healthy)
    with boa.env.prank(caller):
        with boa.reverts("reentrant"):
            controller.liquidate(borrower, 0, WAD, cb.address, b"")


@pytest.mark.parametrize("is_healthy", [True, False])
@pytest.mark.parametrize("different_caller", [True, False])
def test_pps_stable_during_liquidate_full_from_callback(
    different_caller,
    is_healthy,
    controller,
    vault,
    price_oracle,
    admin,
    borrowed_token,
    collateral_token,
    cb,
    seed_liquidity,
):
    """
    pricePerShare/convertToAssets/convertToShares must be identical before,
    during, and after liquidate.

    Position is not underwater; cb covers the full debt.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    if is_healthy:
        assert controller.health(borrower, True) > 0
    else:
        _make_liquidatable(controller, price_oracle, admin, borrower)

    boa.deal(borrowed_token, cb.address, debt)
    cb.set_borrowed_to_return(debt)

    caller = _setup_liquidator(controller, borrower, different_caller, is_healthy)

    before = snapshot(vault)

    with boa.env.prank(caller):
        controller.liquidate(borrower, 0, WAD, cb.address, b"")
        assert not controller.loan_exists(borrower)

    after = snapshot(vault)

    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# Full liquidation from callback (underwater / soft-liquidated)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("is_healthy", [True, False])
@pytest.mark.parametrize("different_caller", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_liquidate_full_from_callback_underwater(
    action,
    different_caller,
    is_healthy,
    controller,
    amm,
    price_oracle,
    admin,
    borrowed_token,
    collateral_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during liquidate callback when the position is
    soft-liquidated (xy[0] > 0).  xy[0] is handled by the AMM; cb covers the
    remaining debt.
    """
    cb.set_action(action)
    cb.set_borrowed_to_return(0)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    _push_underwater(borrower, controller, amm, borrowed_token)
    if is_healthy:
        assert controller.health(borrower, True) > 0
    else:
        _make_liquidatable(controller, price_oracle, admin, borrower)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    boa.deal(borrowed_token, cb.address, debt)
    cb.set_borrowed_to_return(debt)

    caller = _setup_liquidator(controller, borrower, different_caller, is_healthy)
    with boa.env.prank(caller):
        with boa.reverts("reentrant"):
            controller.liquidate(borrower, 0, WAD, cb.address, b"")


@pytest.mark.parametrize("is_healthy", [True, False])
@pytest.mark.parametrize("different_caller", [True, False])
def test_pps_stable_during_liquidate_full_from_callback_underwater(
    different_caller,
    is_healthy,
    controller,
    amm,
    vault,
    price_oracle,
    admin,
    borrowed_token,
    collateral_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after a full liquidation of a
    soft-liquidated position (xy[0] > 0).
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    _push_underwater(borrower, controller, amm, borrowed_token)
    if is_healthy:
        assert controller.health(borrower, True) > 0
    else:
        _make_liquidatable(controller, price_oracle, admin, borrower)

    # cb must cover debt - xy[0]; provide full debt to be safe (excess returned)
    boa.deal(borrowed_token, cb.address, debt)
    cb.set_borrowed_to_return(debt)

    caller = _setup_liquidator(controller, borrower, different_caller, is_healthy)

    before = snapshot(vault)

    with boa.env.prank(caller):
        controller.liquidate(borrower, 0, WAD, cb.address, b"")
        assert not controller.loan_exists(borrower)

    after = snapshot(vault)

    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# Partial liquidation from callback (not underwater)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("is_healthy", [True, False])
@pytest.mark.parametrize("different_caller", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_liquidate_partial_from_callback(
    action,
    different_caller,
    is_healthy,
    controller,
    price_oracle,
    admin,
    borrowed_token,
    collateral_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during a partial liquidate callback (frac=50%).
    Position is not underwater.
    """
    cb.set_action(action)
    cb.set_borrowed_to_return(0)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    if is_healthy:
        assert controller.health(borrower, True) > 0
    else:
        _make_liquidatable(controller, price_oracle, admin, borrower)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    boa.deal(borrowed_token, cb.address, debt)
    cb.set_borrowed_to_return(debt)

    caller = _setup_liquidator(controller, borrower, different_caller, is_healthy)

    with boa.env.prank(caller):
        with boa.reverts("reentrant"):
            controller.liquidate(borrower, 0, _FRAC_HALF, cb.address, b"")


@pytest.mark.parametrize("is_healthy", [True, False])
@pytest.mark.parametrize("different_caller", [True, False])
def test_pps_stable_during_liquidate_partial_from_callback(
    different_caller,
    is_healthy,
    controller,
    vault,
    price_oracle,
    admin,
    borrowed_token,
    collateral_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after a partial liquidation (frac=50%).
    Position is not underwater.
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    if is_healthy:
        assert controller.health(borrower, True) > 0
    else:
        _make_liquidatable(controller, price_oracle, admin, borrower)

    tokens_needed = controller.tokens_to_liquidate(borrower, _FRAC_HALF) + 1
    boa.deal(borrowed_token, cb.address, tokens_needed)
    cb.set_borrowed_to_return(tokens_needed)

    caller = _setup_liquidator(controller, borrower, different_caller, is_healthy)

    before = snapshot(vault)

    with boa.env.prank(caller):
        controller.liquidate(borrower, 0, _FRAC_HALF, cb.address, b"")
        assert controller.loan_exists(borrower)  # partial – position still open

    after = snapshot(vault)

    assert_stable(before, cb, after)


# ---------------------------------------------------------------------------
# Partial liquidation from callback (underwater / soft-liquidated)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("is_healthy", [True, False])
@pytest.mark.parametrize("different_caller", [True, False])
@pytest.mark.parametrize("action", VAULT_OPS)
def test_vault_operation_reverts_in_liquidate_partial_from_callback_underwater(
    action,
    different_caller,
    is_healthy,
    controller,
    amm,
    price_oracle,
    admin,
    borrowed_token,
    collateral_token,
    cb,
    seed_liquidity,
):
    """
    Vault operation must revert during a partial liquidate callback (frac=50%)
    when the position is soft-liquidated (xy[0] > 0).
    """
    cb.set_action(action)
    cb.set_borrowed_to_return(0)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    _push_underwater(borrower, controller, amm, borrowed_token)
    if is_healthy:
        assert controller.health(borrower, True) > 0
    else:
        _make_liquidatable(controller, price_oracle, admin, borrower)

    if action in (ACTION_WITHDRAW, ACTION_REDEEM):
        seed_shares(cb, borrowed_token, WAD + 1)

    # cb covers 1/20
    boa.deal(borrowed_token, cb.address, debt)
    cb.set_borrowed_to_return(debt // 20)

    caller = _setup_liquidator(controller, borrower, different_caller, is_healthy)
    with boa.env.prank(caller):
        with boa.reverts("reentrant"):
            controller.liquidate(borrower, 0, _FRAC_HALF, cb.address, b"")


@pytest.mark.parametrize("is_healthy", [True, False])
@pytest.mark.parametrize("different_caller", [True, False])
def test_pps_stable_during_liquidate_partial_from_callback_underwater(
    different_caller,
    is_healthy,
    controller,
    amm,
    vault,
    price_oracle,
    admin,
    borrowed_token,
    collateral_token,
    cb,
    seed_liquidity,
):
    """
    PPS must be stable before, during, and after a partial liquidation (frac=50%)
    of a soft-liquidated position (xy[0] > 0).
    """
    cb.set_action(ACTION_RECORD)

    debt = seed_liquidity // 10
    borrower = open_max_loan(controller, collateral_token, debt, N)
    _push_underwater(borrower, controller, amm, borrowed_token)
    if is_healthy:
        assert controller.health(borrower, True) > 0
    else:
        _make_liquidatable(controller, price_oracle, admin, borrower)

    tokens_needed = controller.tokens_to_liquidate(borrower, _FRAC_HALF) + 10
    boa.deal(borrowed_token, cb.address, tokens_needed)
    cb.set_borrowed_to_return(tokens_needed)

    caller = _setup_liquidator(controller, borrower, different_caller, is_healthy)

    before = snapshot(vault)

    with boa.env.prank(caller):
        controller.liquidate(borrower, 0, _FRAC_HALF, cb.address, b"")
        assert controller.loan_exists(borrower)  # partial – position still open

    after = snapshot(vault)

    assert_stable(before, cb, after)
