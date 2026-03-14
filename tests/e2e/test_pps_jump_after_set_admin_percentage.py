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
def seed_liquidity(borrowed_token):
    return 1_000_000 * 10 ** borrowed_token.decimals()


def test_set_admin_percentage_totalassets_discontinuity(
    admin,
    vault,
    controller,
    amm,
    monetary_policy,
    borrowed_token,
    collateral_token,
):
    """
    Calling LendController.set_admin_percentage changes Vault.totalAssets()
    discontinuously because pending admin fees are not settled before the new
    percentage is applied.

    totalAssets() = available_balance + total_debt - admin_fees()
    admin_fees()  = stored_fees + pending_interest * admin_percentage

    When admin_percentage changes without first settling the pending interest
    into stored_fees, the retroactive recomputation of admin_fees() causes
    totalAssets() to jump instantly, redistributing value between lenders and
    the admin in a way that was not earned under the new rate.
    """
    seconds_per_year = 365 * 86400
    rate_100_apy = 10**18 // seconds_per_year
    monetary_policy.set_rate(rate_100_apy, sender=admin)
    controller.save_rate(sender=admin)

    initial_pct = WAD // 2  # 50%
    controller.set_admin_percentage(initial_pct, sender=admin)

    # Open a loan to start accumulating interest (and therefore admin fees)
    borrower = boa.env.generate_address("borrower")
    debt = controller.available_balance() // 2
    collateral = 50 * debt * amm.price_oracle() // 10**18
    boa.deal(collateral_token, borrower, collateral)
    with boa.env.prank(borrower):
        collateral_token.approve(controller, MAX_UINT256)
        controller.create_loan(collateral, debt, MIN_TICKS)

    # Let interest (and pending admin fees) accumulate without settling
    boa.env.time_travel(seconds=30 * 86400)  # 30 days

    # Confirm there are unsettled admin fees — this is the precondition for the bug
    pending_fees = controller.admin_fees()
    assert pending_fees > 0, "Expected non-zero pending admin fees before percentage change"

    total_assets_before = vault.totalAssets()

    # Change the admin percentage without settling pending fees first.
    # Lowering the percentage retroactively reduces admin_fees(), which
    # causes totalAssets() to increase discontinuously — a windfall for
    # lenders from interest that was accruing under the old rate.
    new_pct = WAD // 4  # 25%
    controller.set_admin_percentage(new_pct, sender=admin)

    total_assets_after = vault.totalAssets()

    assert total_assets_before == total_assets_after, (
        f"totalAssets changed discontinuously after set_admin_percentage: "
        f"before={total_assets_before}, after={total_assets_after}, "
        f"diff={abs(int(total_assets_after) - int(total_assets_before))}"
    )
