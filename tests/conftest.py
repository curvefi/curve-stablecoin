import os
from datetime import timedelta

import boa
import pytest
from hypothesis import settings, Phase
from tests.utils.deploy import Protocol
from tests.utils.deployers import (
    ERC20_MOCK_DEPLOYER,
    CONSTANT_MONETARY_POLICY_DEPLOYER,
    CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER,
)


boa.env.enable_fast_mode()


PRICE = 3000
TESTING_DECIMALS = [2, 6, 8, 9, 18]


settings.register_profile("no-shrink", settings(phases=list(Phase)[:4]), deadline=timedelta(seconds=1000))
settings.register_profile("default", deadline=timedelta(seconds=1000))
settings.load_profile(os.getenv(u"HYPOTHESIS_PROFILE", "default"))


@pytest.fixture(scope="module")
def proto():
    return Protocol()


@pytest.fixture(scope="module")
def admin(proto):
    return proto.admin


@pytest.fixture(scope="module")
def factory(proto):
    return proto.lending_factory


@pytest.fixture(scope="module")
def stablecoin(proto):
    return proto.crvUSD

@pytest.fixture(scope="module")
def collateral_token():
    # TODO hook decimals fixture
    return ERC20_MOCK_DEPLOYER.deploy(18)


@pytest.fixture(scope="module")
def borrowed_token(stablecoin):
    """Default borrowed token for lending tests (crvUSD).
    Specific test modules can override this if needed.
    """
    # TODO should parametrize to use other tokens
    return stablecoin


@pytest.fixture(scope="module")
def lending_mpolicy_deployer():
    """Default monetary policy deployer for lending markets: Constant policy.
    Tests can override to use a different lending policy.
    """
    return CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER


@pytest.fixture(scope="module")
def monetary_policy(market_type, controller):
    """Monetary policy contract for the current market.
    Test modules can override by replacing the policy on the controller.
    """
    if market_type == "lending":
        # TODO make both controllers use the same policy through a constructor adapter
        return CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER.at(controller.monetary_policy())
    else:
        return CONSTANT_MONETARY_POLICY_DEPLOYER.at(controller.monetary_policy())


@pytest.fixture(scope="module")
def price_oracle(proto):
    return proto.price_oracle


@pytest.fixture(scope="module")
def amm_impl(proto):
    return proto.blueprints.amm


@pytest.fixture(scope="module")
def controller_impl(proto):
    return proto.blueprints.ll_controller


@pytest.fixture(scope="module")
def vault_impl(proto):
    return proto.vault_impl


@pytest.fixture(scope="module")
def price_oracle_impl(proto):
    return proto.blueprints.price_oracle


@pytest.fixture(scope="module")
def mpolicy_impl(proto):
    return proto.blueprints.mpolicy


@pytest.fixture(scope="module", params=["mint", "lending"])
def market_type(request):
    return request.param


@pytest.fixture(scope="module")
def amm_A():
    return 1000


@pytest.fixture(scope="module")
def amm_fee():
    return 10**16


@pytest.fixture(scope="module")
def loan_discount():
    return int(0.09 * 10**18)


@pytest.fixture(scope="module")
def liquidation_discount():
    return int(0.06 * 10**18)


@pytest.fixture(scope="module")
def min_borrow_rate():
    return 10**15 // (365 * 86400)  # 0.1% APR


@pytest.fixture(scope="module")
def max_borrow_rate():
    return 10**18 // (365 * 86400)  # 100% APR


@pytest.fixture(scope="module")
def market(
    market_type,
    proto,
    collateral_token,
    price_oracle,
    seed_liquidity,
    borrowed_token,
    lending_mpolicy_deployer,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    min_borrow_rate,
    max_borrow_rate,
):
    if market_type == "mint":
        return proto.create_mint_market(
            collateral_token=collateral_token,
            price_oracle=price_oracle,
            monetary_policy=proto.mint_monetary_policy,
            A=amm_A,
            amm_fee=amm_fee,
            loan_discount=loan_discount,
            liquidation_discount=liquidation_discount,
            debt_ceiling=seed_liquidity,
        )
    else:
        return proto.create_lending_market(
            borrowed_token=borrowed_token,
            collateral_token=collateral_token,
            A=amm_A,
            fee=amm_fee,
            loan_discount=loan_discount,
            liquidation_discount=liquidation_discount,
            price_oracle=price_oracle,
            name="Test Vault",
            min_borrow_rate=min_borrow_rate,
            max_borrow_rate=max_borrow_rate,
            seed_amount=seed_liquidity,
            mpolicy_deployer=lending_mpolicy_deployer,
        )


@pytest.fixture(scope="module")
def controller(market, market_type, admin, borrow_cap):
    """Controller for the current market (mint or lending).
    Sets borrow cap for lending markets to `borrow_cap`.
    """
    ctrl = market['controller']
    if market_type == "lending" and borrow_cap is not None:
        with boa.env.prank(admin):
            ctrl.set_borrow_cap(borrow_cap)
    return ctrl




@pytest.fixture(scope="module")
def amm(market):
    """AMM for the current market (mint or lending)."""
    return market['amm']


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 1000 * 10**18


@pytest.fixture(scope="module")
def borrow_cap(seed_liquidity):
    """Default borrow cap for lending markets equals `seed_liquidity`.
    Override to adjust or set to None to skip setting. Ignored for mint.
    """
    return seed_liquidity




# ============== Account Fixtures ==============

@pytest.fixture(scope="session")
def accounts():
    return [boa.env.generate_address() for _ in range(10)]


@pytest.fixture(scope="module")
def alice():
    return boa.env.generate_address("alice")


# ============== Token Fixtures ==============

@pytest.fixture(scope="module", params=TESTING_DECIMALS)
def decimals(request):
    return request.param

@pytest.fixture(scope="session")
def token_mock():
    return ERC20_MOCK_DEPLOYER
