"""
E2E test: admin_fees must remain in vault until available_balance covers them.

Scenario:
  1. admin_percentage = 10 %  (small slice goes to admin, most to lenders)
  2. Lender deposits, borrower takes 100 % of available liquidity
  3. Time-travel 1 year → compound interest accrues at 100 % APY (e≈2.718x)
  4. Borrower repays  full_debt - admin_fees()
     → remaining_debt = admin_fees()  (≈ 10 % of accrued interest)
     → stored_admin_fees crystallised = 10 % of accrued interest
     → total_assets = repay_amount = full_debt − admin_fees()  (deposit + 90 % of accrued interest)
  5. Lender redeems max_redeem  → available_balance reduced to admin_fees()
     → admin_fees unchanged: collect_fees() now succeeds (available_balance == admin_fees())

Key numbers (approximate, continuous compound):
  deposit  = 1 M tokens
  year-1 accrued ≈ 1 M × (e−1) ≈ 1.718 M
  admin_fees after repay ≈ 10 % × 1.718 M = 171.8 K
  remaining_debt ≈ 171.8 K
  repay_amount = full_debt − admin_fees() ≈ 2.718 M − 0.172 M ≈ 2.546 M

Key accounting identity:
    total_assets == available_balance + total_debt - admin_fees()
"""

import boa
import pytest

from tests.utils.constants import MIN_TICKS, WAD, MAX_UINT256


@pytest.fixture(scope="module")
def market_type():
    return "lending"


@pytest.fixture(scope="module")
def borrowed_decimals():
    return 18


@pytest.fixture(scope="module")
def collateral_decimals():
    return 18


@pytest.fixture(scope="module")
def borrow_cap():
    return MAX_UINT256


@pytest.fixture(scope="module")
def seed_liquidity():
    return 0


def test_min_total_assets_large_uncollected_fees_pump_pps(
    admin,
    vault,
    controller,
    factory,
    amm,
    monetary_policy,
    borrowed_token,
    collateral_token,
):
    seconds_per_year = 365 * 86400

    # ~100 % APY: maximises compound interest → large admin_fees and strong lender yield
    rate_100_apy = 10**18 // seconds_per_year
    monetary_policy.set_rate(rate_100_apy, sender=admin)
    controller.save_rate(sender=admin)

    # 10 % admin fee: 90 % of interest goes to lenders (PPS pumps hard),
    # while 10 % crystallises as a large pile of uncollected admin_fees.
    controller.set_admin_percentage(WAD // 10, sender=admin)

    # --- Lender deposits ---
    lender = boa.env.generate_address("lender")
    deposit = 1_000_000 * 10**18
    boa.deal(borrowed_token, lender, deposit)
    with boa.env.prank(lender):
        borrowed_token.approve(vault, deposit)
        vault.deposit(deposit)

    initial_pps = vault.pricePerShare()

    # --- Borrower takes out all available liquidity (100 % utilisation) ---
    borrower = boa.env.generate_address("borrower")
    debt = controller.available_balance()
    collateral = 50 * debt * amm.price_oracle() // 10**18
    boa.deal(collateral_token, borrower, collateral)
    with boa.env.prank(borrower):
        collateral_token.approve(controller, MAX_UINT256)
        controller.create_loan(collateral, debt, MIN_TICKS)

    # --- 1 year of compound interest at 100 % APY ---
    boa.env.time_travel(seconds=seconds_per_year)

    with boa.reverts("Available balance exceeded"):
        controller.collect_fees()

    # Repay exactly full_debt - admin_fees().
    # After the call _update_total_debt crystallises the accrued interest:
    #   stored_admin_fees  = 10 % of accrued_interest
    #   remaining_debt     = admin_fees()  (≈ 10 % of accrued_interest)
    #   available_balance += repay_amount  (= full_debt − admin_fees())
    #   total_assets       = available + remaining_debt - stored_admin_fees
    #                      = repay_amount  (= deposit + 90 % of accrued interest)
    full_debt = controller.debt(borrower)
    repay_amount = full_debt - controller.admin_fees()
    boa.deal(borrowed_token, borrower, repay_amount)
    with boa.env.prank(borrower):
        borrowed_token.approve(controller, MAX_UINT256)
        controller.repay(repay_amount)

    max_redeem = vault.maxRedeem(lender)
    max_withdraw = vault.maxWithdraw(lender)
    max_borrowable = controller.max_borrowable(collateral, MIN_TICKS, borrower)
    assert vault.convertToAssets(max_redeem) == controller.available_balance() - controller.admin_fees()
    assert max_withdraw == controller.available_balance() - controller.admin_fees()
    # Lender redeems max_redeem → available_balance shrinks to admin_fees().
    # stored_admin_fees are untouched; collect_fees() now succeeds.
    with boa.reverts("Available balance exceeded"):
        vault.redeem(max_redeem + 1000, sender=lender)

    with boa.reverts("Available balance exceeded"):
        vault.withdraw(max_withdraw + 1, sender=lender)

    with boa.reverts("Available balance exceeded"):
        boa.deal(collateral_token, borrower, collateral)
        controller.borrow_more(collateral, max_borrowable + 1, sender=borrower)

    vault.redeem(max_redeem, sender=lender)

    assert controller.available_balance() == controller.admin_fees()

    pending_fees = controller.admin_fees()
    assert borrowed_token.balanceOf(factory.fee_receiver(controller)) == 0
    controller.collect_fees()
    assert borrowed_token.balanceOf(factory.fee_receiver(controller)) == pending_fees
