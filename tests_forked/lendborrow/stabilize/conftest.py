import pytest
from ape import Contract


@pytest.fixture(scope="module")
def stablecoin_a(project, forked_admin):
    return forked_admin.deploy(project.ERC20Mock, "USDa", "USDa", 6)


@pytest.fixture(scope="module")
def stablecoin_b(project, forked_admin):
    return forked_admin.deploy(project.ERC20Mock, "USDb", "USDb", 18)


@pytest.fixture(scope="module")
def swap_impl(project, forked_admin):
    return forked_admin.deploy(project.Stableswap)


@pytest.fixture(scope="module")
def swap_deployer(project, forked_admin, swap_impl):
    return forked_admin.deploy(project.SwapFactory, swap_impl)


@pytest.fixture(scope="module")
def dummy_tricrypto(project, forked_admin, stablecoin_a):
    tricrypto_contract = forked_admin.deploy(
        project.TricryptoMock,
        [
            stablecoin_a.address,
            "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
            "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        ],
    )

    tricrypto_contract.set_price(0, pytest.default_prices[0], sender=forked_admin)
    tricrypto_contract.set_price(1, pytest.default_prices[1], sender=forked_admin)

    return tricrypto_contract


@pytest.fixture(scope="module")
def price_aggregator(project, forked_admin, stablecoin, stableswap_a, stableswap_b):
    c = forked_admin.deploy(project.AggregateStablePrice, stablecoin.address, 10**15, forked_admin.address)
    c.add_price_pair(stableswap_a.address, sender=forked_admin)
    c.add_price_pair(stableswap_b.address, sender=forked_admin)
    return c


@pytest.fixture(scope="module")
def stableswap_a(project, forked_admin, unsafe_factory, swap_deployer, stablecoin, stablecoin_a):
    trx = swap_deployer.deploy(stablecoin_a, stablecoin, sender=forked_admin)
    assert trx.events[0].receiver == trx.logs[0]["address"]
    return project.Stableswap.at(trx.logs[0]["address"])


@pytest.fixture(scope="module")
def stableswap_b(project, forked_admin, unsafe_factory, swap_deployer, stablecoin, stablecoin_b):
    trx = swap_deployer.invoke_transaction("deploy", stablecoin_b, stablecoin, sender=forked_admin)
    assert trx.events[0].receiver == trx.logs[0]["address"]
    return project.Stableswap.at(trx.logs[0]["address"])


@pytest.fixture(scope="module")
def agg(
    forked_admin,
    stablecoin,
    stablecoin_a,
    stablecoin_b,
    stableswap_a,
    stableswap_b,
    price_aggregator,
):
    stablecoin_a._mint_for_testing(forked_admin, 500000 * 10**6, sender=forked_admin)
    stablecoin_b._mint_for_testing(forked_admin, 500000 * 10**18, sender=forked_admin)

    stablecoin_a.approve(stableswap_a.address, 2**256 - 1, sender=forked_admin)
    stablecoin.approve(stableswap_a.address, 2**256 - 1, sender=forked_admin)
    stablecoin_b.approve(stableswap_b.address, 2**256 - 1, sender=forked_admin)
    stablecoin.approve(stableswap_b.address, 2**256 - 1, sender=forked_admin)

    stableswap_a.add_liquidity([500000 * 10**6, 500000 * 10**18], 0, sender=forked_admin)
    stableswap_b.add_liquidity([500000 * 10**18, 500000 * 10**18], 0, sender=forked_admin)
    yield price_aggregator


@pytest.fixture(scope="module")
def chainlink_aggregator():
    return Contract("0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419")


@pytest.fixture(scope="module")
def crypto_agg_with_external_oracle(project, forked_admin, dummy_tricrypto, agg, stableswap_a, chainlink_aggregator):
    crypto_agg = forked_admin.deploy(
        project.CryptoWithStablePriceAndChainlink,
        dummy_tricrypto.address,
        0,
        stableswap_a,
        agg,
        chainlink_aggregator.address,
        5000,
        1
    )
    crypto_agg.price_w(sender=forked_admin)
    return crypto_agg
