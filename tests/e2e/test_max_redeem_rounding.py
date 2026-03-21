import boa
import pytest

from tests.utils.constants import MIN_TICKS, MAX_UINT256


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


def test_max_redeem_ceiling_causes_revert(
    admin,
    vault,
    controller,
    amm,
    monetary_policy,
    borrowed_token,
    collateral_token,
):
    """
    maxRedeem uses ceiling rounding when converting available_balance to shares.
    When one share is worth more assets than available_balance, the true answer
    is 0 but ceil rounds it up to 1. Calling redeem(1) then reverts.
    """
    seconds_per_year = 365 * 86400

    monetary_policy.set_rate(3 * 10**18 // seconds_per_year)  # 300% APY
    controller.save_rate()
    controller.set_admin_percentage(0, sender=admin)

    deposit_amount = 10**18
    lp = boa.env.generate_address("lp")
    boa.deal(borrowed_token, lp, deposit_amount)
    with boa.env.prank(lp):
        borrowed_token.approve(vault, MAX_UINT256)
        vault.deposit(deposit_amount)

    # Borrow almost everything, leaving 1 wei liquid
    debt = deposit_amount - 1
    collateral = 50 * debt * amm.price_oracle() // 10**18
    borrower = boa.env.generate_address("borrower")
    boa.deal(collateral_token, borrower, collateral)
    with boa.env.prank(borrower):
        collateral_token.approve(controller, MAX_UINT256)
        controller.create_loan(collateral, debt, MIN_TICKS)

    assert controller.available_balance() == 1

    # Time travel until total_assets >> totalSupply + DEAD_SHARES,
    # so one share is worth more than the 1 wei available
    boa.env.time_travel(seconds=10_000 * seconds_per_year)

    assert controller.available_balance() == 1

    # 1 share's worth > 1 — but available_balance = 1
    assert vault.maxRedeem(lp) == 1
    assert vault.previewRedeem(1) > 1

    with boa.reverts("Available balance exceeded"):
        vault.redeem(1, sender=lp)


def test_max_redeem_ceiling_does_not_underestimate(
    admin,
    vault,
    controller,
    amm,
    monetary_policy,
    borrowed_token,
    collateral_token,
):
    """
    _convert_to_shares(..., True) (floor) in maxRedeem can underestimate.
    When total_assets < N (price-per-share < 1 asset), floor truncates the
    fractional share count so that redeeming maxRedeem shares yields 0 assets,
    while redeeming maxRedeem + 1 shares yields exactly available_balance.
    """
    seconds_per_year = 365 * 86400

    monetary_policy.set_rate(10**18 // seconds_per_year)  # 100% APY
    controller.save_rate()
    controller.set_admin_percentage(0, sender=admin)

    deposit_amount = 10**18
    lp = boa.env.generate_address("lp")
    boa.deal(borrowed_token, lp, deposit_amount)
    with boa.env.prank(lp):
        borrowed_token.approve(vault, MAX_UINT256)
        vault.deposit(deposit_amount)

    debt = deposit_amount - 1
    collateral = 50 * debt * amm.price_oracle() // 10**18
    borrower = boa.env.generate_address("borrower")
    boa.deal(collateral_token, borrower, collateral)
    with boa.env.prank(borrower):
        collateral_token.approve(controller, MAX_UINT256)
        controller.create_loan(collateral, debt, MIN_TICKS)

    assert controller.available_balance() == 1

    # Travel 1 year: total_assets grows (stays << N), breaking exact divisibility
    boa.env.time_travel(seconds=seconds_per_year)

    assert controller.available_balance() == 1

    max_r = vault.maxRedeem(lp)

    # ceiling: yields exactly the available balance
    assert vault.previewRedeem(max_r) == 1
    # one less share yields 0 assets — available wei is wasted
    assert vault.previewRedeem(max_r - 1) == 0

    shares_before = vault.balanceOf(lp)
    assets_before = borrowed_token.balanceOf(lp)
    with boa.env.prank(lp):
        vault.redeem(max_r)
    assert vault.balanceOf(lp) == shares_before - max_r
    assert borrowed_token.balanceOf(lp) == assets_before + 1
