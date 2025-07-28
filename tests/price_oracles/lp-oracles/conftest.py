import boa
import pytest
import random

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
        return boa.load('contracts/testing/DummyPriceOracle.vy', admin, random.randint(99 * 10**17, 101 * 10**17))


@pytest.fixture(scope="module")
def get_stable_swap(admin):
    def f(N):
        prices = [random.randint(10**16, 10**23) for i in range(N - 1)]
        with boa.env.prank(admin):
            return boa.load('contracts/price_oracles/lp-oracles/testing/MockStableSwap.vy', admin, prices)

    return f


@pytest.fixture(scope="module")
def crypto_swap(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/lp-oracles/testing/MockCryptoSwap.vy', admin, random.randint(10**16, 10**23))


@pytest.fixture(scope="module")
def stable_swap_no_argument(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/lp-oracles/testing/MockStableSwapNoArgument.vy', admin, random.randint(10**16, 10**23))


@pytest.fixture(scope="module")
def proxy_impl(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/proxy/ProxyOracle.vy')


@pytest.fixture(scope="module")
def proxy_factory(admin, proxy_impl):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/proxy/ProxyOracleFactory.vy', admin, proxy_impl)


@pytest.fixture(scope="module")
def lp_oracle_stable_impl(admin):
    with boa.env.prank(admin):
        return boa.load_partial('contracts/price_oracles/lp-oracles/LPOracleStable.vy').deploy_as_blueprint()


@pytest.fixture(scope="module")
def lp_oracle_crypto_impl(admin):
    with boa.env.prank(admin):
        return boa.load_partial('contracts/price_oracles/lp-oracles/LPOracleCrypto.vy').deploy_as_blueprint()


@pytest.fixture(scope="module")
def lp_oracle_factory(admin, lp_oracle_stable_impl, lp_oracle_crypto_impl, proxy_factory):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/lp-oracles/LPOracleFactory.vy', admin, lp_oracle_stable_impl, lp_oracle_crypto_impl, proxy_factory)


@pytest.fixture(scope="module")
def get_lp_oracle_stable(admin):
    def f(pool, coin0_oracle):
        with boa.env.prank(admin):
            return boa.load('contracts/price_oracles/lp-oracles/LPOracleStable.vy', pool, coin0_oracle)

    return f


@pytest.fixture(scope="module")
def get_lp_oracle_crypto(admin):
    def f(pool, coin0_oracle):
        with boa.env.prank(admin):
            return boa.load('contracts/price_oracles/lp-oracles/LPOracleCrypto.vy', pool, coin0_oracle)

    return f
