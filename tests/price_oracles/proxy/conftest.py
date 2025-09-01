import boa
import pytest
from tests.utils.deployers import (
    DUMMY_PRICE_ORACLE_DEPLOYER,
    WETH_DEPLOYER,
    PROXY_ORACLE_DEPLOYER,
    PROXY_ORACLE_FACTORY_DEPLOYER
)


@pytest.fixture(scope="session")
def user(accounts):
    return accounts[0]


@pytest.fixture(scope="module")
def get_price_oracle(admin):
    def f(price):
        with boa.env.prank(admin):
            oracle = DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, price)
            return oracle

    return f


@pytest.fixture(scope="module")
def broken_price_oracle(admin):
    with boa.env.prank(admin):
        oracle = WETH_DEPLOYER.deploy()
        return oracle


@pytest.fixture(scope="module")
def proxy_impl(admin):
    with boa.env.prank(admin):
        return PROXY_ORACLE_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def proxy_factory(admin, proxy_impl):
    with boa.env.prank(admin):
        return PROXY_ORACLE_FACTORY_DEPLOYER.deploy(admin, proxy_impl)
