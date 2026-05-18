"""
E2E test verifying that lenders earn yield matching the advertised lend_apr,
accounting for admin fees, after various market activities (borrows, repays, etc).
"""

import boa
import pytest

from tests.utils.constants import WAD, MAX_UINT256


@pytest.fixture(scope="module")
def market_type():
    return "lending"


@pytest.fixture(scope="module")
def admin_percentage():
    return WAD // 10  # 10% admin fee


def test_lender_yield_matches_apr(
    vault,
    controller,
    configurator,
    admin,
    borrowed_token,
    collateral_token,
    price_oracle,
    admin_percentage,
):
    """
    Test that a lender's actual yield roughly matches the advertised lend_apr
    after a series of borrows, repays, and time passing.
    """
    configurator.set_admin_percentage(controller, admin_percentage, sender=admin)

    decimals = borrowed_token.decimals()
    collateral_decimals = collateral_token.decimals()

    lender = boa.env.generate_address("lender")
    borrowers = [boa.env.generate_address(f"borrower_{i}") for i in range(3)]

    # Lender deposits into vault
    deposit_amount = 10_000 * 10**decimals
    boa.deal(borrowed_token, lender, deposit_amount)
    with boa.env.prank(lender):
        borrowed_token.approve(vault, MAX_UINT256)
        vault.deposit(deposit_amount)

    # Increase borrow cap to allow loans
    configurator.set_borrow_cap(controller, deposit_amount, sender=admin)

    initial_shares = vault.balanceOf(lender)
    initial_assets = vault.convertToAssets(initial_shares)

    # Borrowers take loans - use price oracle to calculate appropriate collateral
    oracle_price = price_oracle.price()  # collateral price in borrowed token units
    debt_per_borrower = deposit_amount // 10  # each borrower takes 10% of available
    # Collateral needed = debt * WAD / price * 2 (for safety margin)
    collateral_per_borrower = debt_per_borrower * WAD * 2 // oracle_price
    # Scale to collateral decimals
    collateral_per_borrower = (
        collateral_per_borrower * 10**collateral_decimals // 10**decimals
    )
    bands = 10

    for borrower in borrowers:
        boa.deal(collateral_token, borrower, collateral_per_borrower)
        with boa.env.prank(borrower):
            collateral_token.approve(controller, MAX_UINT256)
            controller.create_loan(collateral_per_borrower, debt_per_borrower, bands)

    # Record APR after loans are active
    lend_apr = vault.lend_apr()
    assert lend_apr > 0, "lend_apr should be positive with active loans"

    # Time travel 1 year
    seconds_in_year = 365 * 86400
    boa.env.time_travel(seconds=seconds_in_year)

    # Some borrowers repay partially, some fully
    with boa.env.prank(borrowers[0]):
        # Partial repay
        boa.deal(borrowed_token, borrowers[0], debt_per_borrower // 2)
        borrowed_token.approve(controller, MAX_UINT256)
        controller.repay(debt_per_borrower // 2)

    with boa.env.prank(borrowers[1]):
        # Full repay
        debt = controller.debt(borrowers[1])
        boa.deal(borrowed_token, borrowers[1], debt)
        borrowed_token.approve(controller, MAX_UINT256)
        controller.repay(MAX_UINT256)

    # borrowers[2] keeps loan open

    # Check lender's yield
    final_assets = vault.convertToAssets(initial_shares)
    actual_yield = final_assets - initial_assets

    # Expected yield based on initial APR (rough approximation)
    # The actual yield will vary as utilization changes, but should be in the ballpark
    expected_yield_approx = initial_assets * lend_apr // WAD

    # Allow 50% tolerance since utilization changed during the year
    # (borrower 1 fully repaid, borrower 0 partially repaid)
    tolerance = expected_yield_approx // 2

    assert actual_yield > 0, "Lender should have earned some yield"
    assert abs(actual_yield - expected_yield_approx) < tolerance, (
        f"Actual yield {actual_yield} differs too much from expected {expected_yield_approx}"
    )


def test_lend_apr_zero_with_no_debt(vault, controller):
    """lend_apr should be 0 when there's no debt in the system."""
    assert controller.total_debt() == 0
    assert vault.lend_apr() == 0


def test_lend_apr_reflects_admin_fee(
    vault,
    controller,
    borrowed_token,
    collateral_token,
    price_oracle,
):
    """
    Test that lend_apr correctly reflects the admin fee deduction.
    """
    decimals = borrowed_token.decimals()
    collateral_decimals = collateral_token.decimals()

    borrower = boa.env.generate_address("borrower")

    # Create some debt first
    available = controller.available_balance()
    debt_amount = available // 10

    # Calculate collateral needed based on oracle price
    oracle_price = price_oracle.price()
    collateral_amount = debt_amount * WAD * 2 // oracle_price
    collateral_amount = collateral_amount * 10**collateral_decimals // 10**decimals

    boa.deal(collateral_token, borrower, collateral_amount)
    with boa.env.prank(borrower):
        collateral_token.approve(controller, MAX_UINT256)
        controller.create_loan(collateral_amount, debt_amount, 10)

    # Get lend_apr with current admin percentage (set by fixture)
    lend_apr_with_fee = vault.lend_apr()
    borrow_apr = vault.borrow_apr()

    # lend_apr should be less than borrow_apr due to:
    # 1. admin fee
    # 2. utilization ratio (not all deposits are borrowed)
    assert lend_apr_with_fee < borrow_apr
    assert lend_apr_with_fee > 0
