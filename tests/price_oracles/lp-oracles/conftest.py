import boa
import pytest

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


@pytest.fixture(scope="session")
def user(accounts):
    return accounts[0]


@pytest.fixture(scope="module")
def broken_contract(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/WETH.vy')


@pytest.fixture(scope="module")
def coin0_oracle(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/DummyPriceOracle.vy', admin, 10**18)


@pytest.fixture(scope="module")
def get_stable_swap(admin):
    def f(N):
        prices = [10**18] * (N - 1)
        with boa.env.prank(admin):
            return boa.load('contracts/price_oracles/lp-oracles/testing/MockStableSwap.vy', admin, prices)

    return f


@pytest.fixture(scope="module")
def crypto_swap(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/lp-oracles/testing/MockCryptoSwap.vy', admin, 10**18)


@pytest.fixture(scope="module")
def stable_swap_no_argument(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/lp-oracles/testing/MockStableSwapNoArgument.vy', admin, 10**18)


@pytest.fixture(scope="module")
def proxy_impl(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/proxy/ProxyOracle.vy')


@pytest.fixture(scope="module")
def proxy_factory(admin, proxy_impl):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/proxy/ProxyOracleFactory.vy', admin, proxy_impl)


@pytest.fixture(scope="module")
def stable_oracle_impl(admin):
    with boa.env.prank(admin):
        return boa.load_partial('contracts/price_oracles/lp-oracles/LPOracleStable.vy').deploy_as_blueprint()


@pytest.fixture(scope="module")
def crypto_oracle_impl(admin):
    with boa.env.prank(admin):
        return boa.load_partial('contracts/price_oracles/lp-oracles/LPOracleCrypto.vy').deploy_as_blueprint()


@pytest.fixture(scope="module")
def lp_oracle_factory(admin, stable_oracle_impl, crypto_oracle_impl, proxy_factory):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/lp-oracles/LPOracleFactory.vy', admin, stable_oracle_impl, crypto_oracle_impl, proxy_factory)
