import boa
import pytest

from tests.utils import max_approve
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


def _ceil_div(n: int, d: int) -> int:
    return (n + d - 1) // d


def test_checkout_collect_fees_changes_withdraw_terms(
    admin,
    vault,
    controller,
    configurator,
    amm,
    monetary_policy,
    borrowed_token,
    collateral_token,
):
    # 1) Configure lending protocol: done by fixtures (lending market)

    # 2) Set rate with 100% APY (per-second rate, 1e18-based)
    seconds_per_year = 365 * 86400
    rate_100_apy = 10**18 // seconds_per_year
    monetary_policy.set_rate(rate_100_apy, sender=admin)
    controller.save_rate(sender=admin)

    # 3) Set admin fees portion
    admin_pct = WAD // 2  # 50%
    configurator.set_admin_percentage(controller, admin_pct, sender=admin)

    # 4) Make first deposit in Vault to have liquidity in Controller
    lp = boa.env.generate_address("lp")
    lp_assets = 1_000_000 * 10 ** borrowed_token.decimals()
    boa.deal(borrowed_token, lp, lp_assets)
    with boa.env.prank(lp):
        borrowed_token.approve(vault, lp_assets)
        vault.deposit(lp_assets)

    # 5) Take loan to start accumulating borrow APR
    borrower = boa.env.generate_address("borrower")
    debt = lp_assets // 2

    collateral = 50 * debt * amm.price_oracle() // 10**18
    boa.deal(collateral_token, borrower, collateral)
    max_approve(collateral_token, controller, sender=borrower)
    with boa.env.prank(borrower):
        controller.create_loan(collateral, debt, MIN_TICKS)

    attacker = boa.env.generate_address("attacker")
    attacker_assets = 10_000 * 10 ** borrowed_token.decimals()

    def scenario(*, do_collect_fees: bool) -> int:
        with boa.env.anchor():
            # 6) From this state, demonstrate two scenarios:
            # 6.1 / 6.2) Attacker deposit
            boa.deal(borrowed_token, attacker, attacker_assets)
            with boa.env.prank(attacker):
                borrowed_token.approve(vault, attacker_assets)
                vault.deposit(attacker_assets)

            print("--------------------------------")
            if do_collect_fees:
                print("With prior collecting/updating fees")
            else:
                print("Without prior collecting/updating fees")

            print("Attacker deposit", attacker_assets)
            print(
                "Available balance before time travel", controller.available_balance()
            )
            print("Total assets before time travel", vault.totalAssets())

            # Wait 12 seconds (simulate 1 block)
            boa.env.time_travel(seconds=12)

            # 6.2) Optional checkout (collect_fees)
            collected_now = 0
            if do_collect_fees:
                collected_now = controller.collect_fees(sender=attacker)

            print("Available balance after time travel", controller.available_balance())
            print("Total assets after time travel", vault.totalAssets())

            # Withdraw: take the maximum withdrawable amount for attacker
            max_w = vault.maxWithdraw(attacker)
            with boa.env.prank(attacker):
                vault.withdraw(max_w)

            print("Attacker withdraw", max_w)
            print("Attacker balance after withdraw", borrowed_token.balanceOf(attacker))

            return max_w

    # 6.1) No fee checkout: admin_fees not up-to-date (collected stays 0)
    max_w_no_collect = scenario(do_collect_fees=False)

    # 6.2) With fee checkout: fees up-to-date (collect_fees updates + transfers)
    max_w_with_collect = scenario(do_collect_fees=True)

    print("--------------------------------")
    print("Difference in withdraw", abs(max_w_with_collect - max_w_no_collect))
    print("--------------------------------")

    assert max_w_with_collect == max_w_no_collect
