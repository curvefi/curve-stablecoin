"""
Regression: accrued `admin_fees` at 100% utilization must not brick `save_rate()`

Both v2 hyperbolic policies used to compute reserves as

    total_reserves = available_balance + total_debt - admin_fees

which subtracts the fees from the reserves but not from the debt, so
`assert total_reserves >= total_debt, "Reserves too small"` was really
`assert available_balance >= admin_fees`. Once a market was fully utilized
(`available_balance == 0`), any non-zero accrued admin fee reverted the policy,
and with it every Controller entrypoint that saves the rate (create_loan /
borrow_more / repay / liquidate / collect_fees / ...) - even repaying, which is
what would have restored the liquidity. Recovery required a donation of
borrowed token to the Controller.

`_get_utilization` now nets the fees out of the available balance only, floored
at zero, matching `LendControllerView._get_cap`.

Flow (identical for both policies):
  * lender deposits into the vault
  * borrower borrows the entire available balance -> u = 100%
  * time travel -> interest accrues -> admin_fees > 0
  * save_rate() still works, u pins at 100%, and the market stays usable
"""

import boa
import pytest

from tests.utils import max_approve
from tests.utils.constants import MAX_UINT256, MIN_TICKS
from tests.utils.deployers import (
    HYPERBOLIC_DYNAMIC_MP_DEPLOYER,
    HYPERBOLIC_MP_DEPLOYER,
    MOCK_RATE_CALCULATOR_DEPLOYER,
)

WAD = 10**18

TARGET_UTILIZATION = 85 * 10**16
LOW_RATIO = 5 * 10**17
HIGH_RATIO = 3 * 10**18
RATE_SHIFT = 0
TARGET_RATE = 10**17 // (365 * 86400)  # 10% APR, per second

ADMIN_PERCENTAGE = 10**17  # 10% of interest goes to admin fees

DEPOSIT = 1000 * 10**18
COLLATERAL = 1000 * 10**18


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
def seed_liquidity():
    return 0


@pytest.fixture(scope="module")
def borrow_cap():
    return MAX_UINT256


# Each test drives its market into full utilization, so they get a fresh one
# (the shared fixtures in tests/conftest.py are module-scoped).
@pytest.fixture
def market(
    proto,
    borrowed_token,
    collateral_token,
    price_oracle,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    min_borrow_rate,
    max_borrow_rate,
):
    return proto.create_lending_market(
        borrowed_token=borrowed_token,
        collateral_token=collateral_token,
        A=amm_A,
        fee=amm_fee,
        loan_discount=loan_discount,
        liquidation_discount=liquidation_discount,
        price_oracle=price_oracle,
        min_borrow_rate=min_borrow_rate,
        max_borrow_rate=max_borrow_rate,
        seed_amount=0,
    )


@pytest.fixture
def controller(market, configurator, admin, borrow_cap):
    ctrl = market["controller"]
    configurator.set_borrow_cap(ctrl, borrow_cap, sender=admin)
    # Lending markets start at 0%; any non-zero share of the interest is enough.
    configurator.set_admin_percentage(ctrl, ADMIN_PERCENTAGE, sender=admin)
    return ctrl


@pytest.fixture
def vault(market):
    return market["vault"]


@pytest.fixture
def hyperbolic_mp(controller, configurator, admin):
    """HyperbolicMP installed on the live market."""
    mp = HYPERBOLIC_MP_DEPLOYER.deploy(
        controller.address,
        TARGET_UTILIZATION,
        TARGET_RATE,
        LOW_RATIO,
        HIGH_RATIO,
        RATE_SHIFT,
    )
    configurator.set_monetary_policy(controller, mp, sender=admin)
    return mp


@pytest.fixture
def hyperbolic_dynamic_mp(controller, configurator, admin):
    """HyperbolicDynamicMP (with a mock rate calculator) installed on the live market."""
    rate_calculator = MOCK_RATE_CALCULATOR_DEPLOYER.deploy(TARGET_RATE)
    mp = HYPERBOLIC_DYNAMIC_MP_DEPLOYER.deploy(
        controller.address,
        rate_calculator.address,
        TARGET_UTILIZATION,
        LOW_RATIO,
        HIGH_RATIO,
        RATE_SHIFT,
    )
    configurator.set_monetary_policy(controller, mp, sender=admin)
    return mp


def _borrow_everything(vault, controller, borrowed_token, collateral_token):
    """Lender deposits, borrower takes out the whole available balance."""
    lender = boa.env.generate_address("lender")
    borrower = boa.env.generate_address("borrower")

    boa.deal(borrowed_token, lender, DEPOSIT)
    boa.deal(collateral_token, borrower, COLLATERAL)

    with boa.env.prank(lender):
        max_approve(borrowed_token, vault.address)
        vault.deposit(DEPOSIT)

    with boa.env.prank(borrower):
        max_approve(collateral_token, controller.address)
        max_approve(borrowed_token, controller.address)
        debt = controller.available_balance()
        controller.create_loan(COLLATERAL, debt, MIN_TICKS)

    # Fully utilized: nothing left in the controller.
    assert controller.available_balance() == 0
    assert controller.total_debt() == debt

    return borrower


def _assert_survives_admin_fees(controller, mp, borrowed_token, borrower):
    # No fees accrued yet.
    assert controller.admin_fees() == 0
    controller.save_rate()

    # Time travel so that interest (and therefore admin fees) accrues.
    boa.env.time_travel(seconds=86400)

    # available_balance == 0 < admin_fees: the state that used to revert.
    assert controller.available_balance() == 0
    assert controller.admin_fees() > 0

    # The policy pins utilization at 100% (rate at the top of the curve, i.e.
    # target_rate * high_ratio) instead of reverting.
    p = mp.parameters()
    expected_top = (
        TARGET_RATE * p.r_minf // WAD
        + p.A * TARGET_RATE // (p.u_inf - WAD)
        + p.rate_shift
    )
    assert mp.rate() == expected_top
    controller.save_rate()

    # And the market is still usable: the borrower can repay.
    debt = controller.debt(borrower)
    boa.deal(borrowed_token, borrower, debt)
    with boa.env.prank(borrower):
        controller.repay(debt)
    assert controller.debt(borrower) == 0

    # Fees are now covered by the balance, and the rate keeps working.
    assert controller.available_balance() > controller.admin_fees()
    assert mp.rate() > 0


def test_hyperbolic_mp_survives_admin_fees_at_full_utilization(
    vault,
    controller,
    borrowed_token,
    collateral_token,
    hyperbolic_mp,
):
    borrower = _borrow_everything(vault, controller, borrowed_token, collateral_token)
    _assert_survives_admin_fees(controller, hyperbolic_mp, borrowed_token, borrower)


def test_hyperbolic_dynamic_mp_survives_admin_fees_at_full_utilization(
    vault,
    controller,
    borrowed_token,
    collateral_token,
    hyperbolic_dynamic_mp,
):
    borrower = _borrow_everything(vault, controller, borrowed_token, collateral_token)
    _assert_survives_admin_fees(
        controller, hyperbolic_dynamic_mp, borrowed_token, borrower
    )
