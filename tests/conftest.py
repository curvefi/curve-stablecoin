import os
from datetime import timedelta

import boa
import pytest
from hypothesis import settings, Phase
from tests.utils.deploy import Protocol
from tests.utils.deployers import (
    ERC20_MOCK_DEPLOYER, 
    DUMMY_PRICE_ORACLE_DEPLOYER
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


@pytest.fixture(scope="module")
def collateral_token():
    return ERC20_MOCK_DEPLOYER.deploy(18)


@pytest.fixture(scope="module")
def borrowed_token(decimals):
    """Parametrized borrowed token using the global `decimals` list."""
    return ERC20_MOCK_DEPLOYER.deploy(decimals)
