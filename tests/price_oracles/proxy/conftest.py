import boa
import pytest


@pytest.fixture(scope="session")
def user(accounts):
    return accounts[0]


@pytest.fixture(scope="session")
def get_price_oracle(admin):
    def f(price):
        with boa.env.prank(admin):
            oracle = boa.load('contracts/testing/DummyPriceOracle.vy', admin, price)
            return oracle

    return f


@pytest.fixture(scope="session")
def broken_price_oracle(admin):
    with boa.env.prank(admin):
        oracle = boa.load('contracts/testing/WETH.vy')
        return oracle


@pytest.fixture(scope="module")
def proxy_impl(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/proxy/ProxyOracle.vy')


@pytest.fixture(scope="module")
def proxy_factory(admin, proxy_impl):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/proxy/ProxyOracleFactory.vy', admin, proxy_impl)
