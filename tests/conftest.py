from datetime import timedelta

import boa
import pytest
from hypothesis import settings, Phase
from tests.utils.deployers import (
    ERC20_MOCK_DEPLOYER,
    CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER,
    FAKE_LEVERAGE_DEPLOYER,
    DUMMY_CALLBACK_DEPLOYER,
)
from tests.utils.protocols import Llamalend

boa.env.enable_fast_mode()


TESTING_DECIMALS = [2, 18]


no_shrink = settings.register_profile(
    "no-shrink",
    phases=list(Phase)[:4],
    deadline=timedelta(seconds=1000),
    print_blob=True,
)
settings.register_profile(
    "quick",
    parent=no_shrink,
    max_examples=3,
    stateful_step_count=15,
)

settings.load_profile("no-shrink")


@pytest.fixture(scope="module")
def proto():
    return Llamalend()


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
def collateral_token(collateral_decimals):
    return ERC20_MOCK_DEPLOYER.deploy(collateral_decimals)


@pytest.fixture(scope="module")
def borrowed_token(market_type, stablecoin, borrowed_decimals):
    """Borrowed token for markets.
    - Mint markets always use crvUSD (stablecoin).
    - Lending markets use a mock token with parameterized decimals.
    """
    if market_type == "mint":
        return stablecoin
    return ERC20_MOCK_DEPLOYER.deploy(borrowed_decimals)


@pytest.fixture(scope="module")
def fake_leverage(controller, collateral_token, borrowed_token, price_oracle):
    market_price = price_oracle.price()
    leverage = FAKE_LEVERAGE_DEPLOYER.deploy(
        borrowed_token.address,
        collateral_token.address,
        controller.address,
        market_price,
    )
    return leverage


@pytest.fixture(scope="module")
def dummy_callback():
    return DUMMY_CALLBACK_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def mint_monetary_policy(proto):
    return proto.mint_monetary_policy


@pytest.fixture(scope="module")
def lending_monetary_policy():
    """Default monetary policy deployer for lending markets (override in suites)."""
    return CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER


@pytest.fixture(scope="module")
def monetary_policy(
    market_type, controller, mint_monetary_policy, lending_monetary_policy
):
    """Actual monetary policy contract bound to this market (post-creation)."""
    if market_type == "mint":
        return mint_monetary_policy
    return lending_monetary_policy.at(controller.monetary_policy())


@pytest.fixture(scope="module")
def price_oracle(proto):
    return proto.price_oracle


@pytest.fixture(scope="module")
def amm_impl(proto):
    return proto.blueprints.amm


@pytest.fixture(scope="module")
def controller_impl(proto):
    return proto.blueprints.lend_controller


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
    return 100


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
    mint_monetary_policy,
    lending_monetary_policy,
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
            monetary_policy=mint_monetary_policy,
            A=amm_A,
            amm_fee=amm_fee,
            loan_discount=loan_discount,
            liquidation_discount=liquidation_discount,
            debt_ceiling=seed_liquidity,
        )
    elif market_type == "lending":
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
            mpolicy_deployer=lending_monetary_policy,
        )
    else:
        raise ValueError("Incorrect market type fixture")


@pytest.fixture(scope="module")
def controller(market, market_type, admin, borrow_cap):
    """Controller for the current market (mint or lending).
    Sets borrow cap for lending markets to `borrow_cap`.
    """
    ctrl = market["controller"]
    if market_type == "lending" and borrow_cap is not None:
        with boa.env.prank(admin):
            ctrl.set_borrow_cap(borrow_cap)
    return ctrl


@pytest.fixture(scope="module")
def amm(market):
    """AMM for the current market (mint or lending)."""
    return market["amm"]


@pytest.fixture(scope="module")
def vault(market, market_type):
    """Vault for the current market (mint or lending).
    Mint markets do not have a vault; return None in that case.
    """
    if market_type == "lending":
        return market["vault"]
    return None


@pytest.fixture(scope="module")
def seed_liquidity(borrowed_token):
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 1000 * 10 ** borrowed_token.decimals()


@pytest.fixture(scope="module")
def borrow_cap(seed_liquidity):
    """Default borrow cap for lending markets equals `seed_liquidity`.
    Override to adjust or set to None to skip setting. Ignored for mint.
    """
    return seed_liquidity


# ============== Account Fixtures ==============


# Deprecated everywhere: prefer inline role-named addresses.
@pytest.fixture(scope="session")
def accounts():
    return [boa.env.generate_address() for _ in range(10)]


# Deprecated everywhere: prefer inline role-named addresses.
@pytest.fixture(scope="module")
def alice():
    return boa.env.generate_address("alice")


# ============== Token Fixtures ==============


@pytest.fixture(scope="module", params=TESTING_DECIMALS)
def collateral_decimals(request):
    return request.param


@pytest.fixture(scope="module", params=TESTING_DECIMALS)
def borrowed_decimals(request):
    """@notice Don't use this fixture in tests because for mint markets borrowed decimals are always 18. Use"""
    return request.param


@pytest.fixture(scope="session")
def token_mock():
    return ERC20_MOCK_DEPLOYER
