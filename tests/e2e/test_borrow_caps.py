import boa
import pytest

from tests.utils.constants import MAX_UINT256

N_BANDS = 5


@pytest.fixture(scope="module")
def amounts(collateral_token, borrowed_token):
    return {
        "collateral": int(0.1 * 10 ** collateral_token.decimals()),
        "extra_collateral": int(0.1 * 10 ** collateral_token.decimals()),
        "premint_collateral": int(10**6 * 10 ** collateral_token.decimals()),
        "premint_borrowed": int(10**6 * 10 ** borrowed_token.decimals()),
    }


@pytest.fixture(scope="module")
def market_type():
    # Borrow caps don't apply to mint markets
    return "lending"


@pytest.fixture(scope="module")
def borrow_cap():
    # Start with zero cap to recreate the conditions of a freshly deployed market
    return 0


def test_borrow_cap(controller, admin, collateral_token, borrowed_token, amounts):
    # Pre-mint ample balances and approvals for the default EOA
    boa.deal(collateral_token, boa.env.eoa, amounts["premint_collateral"])
    boa.deal(borrowed_token, boa.env.eoa, amounts["premint_borrowed"])
    collateral_token.approve(controller, MAX_UINT256)
    borrowed_token.approve(controller, MAX_UINT256)

    # Borrow cap is zero at deployment; any loan should revert
    assert controller.borrow_cap() == 0
    with boa.reverts("Borrow cap exceeded"):
        controller.create_loan(amounts["collateral"], 1, N_BANDS)

    # Raise the cap modestly and open a loan that consumes the allowance
    debt_cap = 1
    controller.set_borrow_cap(debt_cap, sender=admin)
    assert controller.available_balance() > 0
    controller.create_loan(amounts["collateral"], debt_cap, N_BANDS)
    assert controller.available_balance() > 0
    assert controller.total_debt() == debt_cap

    # Attempts to borrow beyond the cap should revert
    with boa.reverts("Borrow cap exceeded"):
        controller.borrow_more(0, 1)

    # Increase collateral, temporarily lift the cap, and borrow more within the new limit
    controller.add_collateral(amounts["extra_collateral"])
    controller.set_borrow_cap(MAX_UINT256, sender=admin)
    collateral_locked, _, current_debt, bands = controller.user_state(boa.env.eoa)
    max_total = controller.max_borrowable(
        collateral_locked, bands, current_debt, boa.env.eoa
    )
    extra_debt = max_total - current_debt
    assert extra_debt > 0
    controller.set_borrow_cap(current_debt + extra_debt, sender=admin)
    assert controller.available_balance() > 0
    controller.borrow_more(0, extra_debt)
    assert controller.available_balance() > 0
    assert controller.total_debt() == current_debt + extra_debt

    # Cutting the cap back to zero blocks further borrowing but allows repayments
    controller.set_borrow_cap(0, sender=admin)
    with boa.reverts("Borrow cap exceeded"):
        controller.borrow_more(0, 1)

    # Repay the full position and exit cleanly
    assert controller.available_balance() > 0
    controller.repay(MAX_UINT256)
    assert controller.available_balance() > 0
    remaining_collateral, _, debt_after_repay, _ = controller.user_state(boa.env.eoa)
    assert debt_after_repay == 0
    if remaining_collateral > 0:
        controller.remove_collateral(remaining_collateral)

    # With a zero cap, opening a fresh loan remains disallowed
    with boa.reverts("Borrow cap exceeded"):
        controller.create_loan(amounts["collateral"], 1, N_BANDS)
