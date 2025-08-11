import boa
import pytest
from .settings import WEB3_PROVIDER_URL, EXPLORER_URL, EXPLORER_TOKEN


@pytest.fixture(scope="module", autouse=True)
def boa_fork():
    assert WEB3_PROVIDER_URL is not None, "Provider url is not set, add WEB3_PROVIDER_URL param to env"
    boa.fork(WEB3_PROVIDER_URL)


@pytest.fixture(scope="module")
def stablecoin_aggregator():
    return boa.from_etherscan("0x18672b1b0c623a30089A280Ed9256379fb0E4E62", "AggregatorStablePrice", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)  # USD/crvUSD


@pytest.fixture(scope="module")
def admin():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def trader():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def stable_impl(admin):
    with boa.env.prank(admin):
        return boa.load_partial('contracts/price_oracles/lp-oracles/LPOracleStable.vy').deploy_as_blueprint()


@pytest.fixture(scope="module")
def crypto_impl(admin):
    with boa.env.prank(admin):
        return boa.load_partial('contracts/price_oracles/lp-oracles/LPOracleCrypto.vy').deploy_as_blueprint()


@pytest.fixture(scope="module")
def proxy_impl(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/proxy/ProxyOracle.vy')


@pytest.fixture(scope="module")
def proxy_factory(admin, proxy_impl):
    with boa.env.prank(admin):
        return boa.load('contracts/price_oracles/proxy/ProxyOracleFactory.vy', admin, proxy_impl)


@pytest.fixture(scope="module")
def lp_oracle_factory(admin, stable_impl, crypto_impl, proxy_factory):
    with boa.env.prank(admin):
        factory = boa.load("contracts/price_oracles/lp-oracles/LPOracleFactory.vy", admin, stable_impl, crypto_impl, proxy_factory)
        return factory
