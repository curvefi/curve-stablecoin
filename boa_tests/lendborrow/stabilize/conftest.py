import boa
import pytest
from boa.contract import VyperContract


@pytest.fixture(scope="module")
def stablecoin_a(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "USDa", "USDa", 6)


@pytest.fixture(scope="module")
def stablecoin_b(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "USDb", "USDb", 18)


@pytest.fixture(scope="module")
def swap_impl(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/Stableswap.vy')


@pytest.fixture(scope="module")
def swap_deployer(swap_impl, admin):
    with boa.env.prank(admin):
        deployer = boa.load('contracts/testing/SwapFactory.vy', swap_impl.address)
        return deployer


@pytest.fixture(scope="module")
def unsafe_factory(controller_factory, stablecoin, admin, accounts):
    with boa.env.anchor():
        with boa.env.prank(admin):
            # Give admin ability to mint coins for testing (don't do that at home!)
            controller_factory.set_debt_ceiling(admin, 10**6 * 10**18)
        yield controller_factory


@pytest.fixture(scope="module")
def stableswap_a(unsafe_factory, swap_deployer, swap_impl, stablecoin, stablecoin_a, admin):
    with boa.env.prank(admin):
        n = swap_deployer.n()
        swap_deployer.deploy(stablecoin_a, stablecoin)
        addr = swap_deployer.pools(n)
        swap = VyperContract(
            swap_impl.compiler_data,
            override_address=addr
        )
        return swap


@pytest.fixture(scope="module")
def stableswap_b(unsafe_factory, swap_deployer, swap_impl, stablecoin, stablecoin_b, admin):
    with boa.env.prank(admin):
        n = swap_deployer.n()
        swap_deployer.deploy(stablecoin_b, stablecoin)
        addr = swap_deployer.pools(n)
        swap = VyperContract(
            swap_impl.compiler_data,
            override_address=addr
        )
        return swap


@pytest.fixture(scope="module")
def price_aggregator(stablecoin, stableswap_a, stableswap_b, admin):
    with boa.env.prank(admin):
        agg = boa.load('contracts/price_oracles/AggregateStablePrice.vy', stablecoin.address, 10**15)
        agg.add_price_pair(stableswap_a.address)
        agg.add_price_pair(stableswap_b.address)
        return agg


@pytest.fixture(scope="module")
def dummy_tricrypto(stablecoin_a, admin):
    with boa.env.prank(admin):
        pool = boa.load('contracts/testing/TricryptoMock.vy',
                        [stablecoin_a.address,
                         "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                         "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"])
        pool.set_price(0, 3000 * 10**18)
        pool.set_price(1, 20000 * 10**18)
        return pool


@pytest.fixture(scope="module")
def agg(stablecoin, stablecoin_a, stablecoin_b, stableswap_a, stableswap_b, price_aggregator, admin):
    with boa.env.anchor():
        with boa.env.prank(admin):
            stablecoin_a._mint_for_testing(admin, 500000 * 10**6)
            stablecoin_b._mint_for_testing(admin, 500000 * 10**18)

            stablecoin_a.approve(stableswap_a.address, 2**256-1)
            stablecoin.approve(stableswap_a.address, 2**256-1)
            stablecoin_b.approve(stableswap_b.address, 2**256-1)
            stablecoin.approve(stableswap_b.address, 2**256-1)

            stableswap_a.add_liquidity([500000 * 10**6, 500000 * 10**18], 0)
            stableswap_b.add_liquidity([500000 * 10**18, 500000 * 10**18], 0)
        yield price_aggregator


@pytest.fixture(scope="module")
def crypto_agg(dummy_tricrypto, agg, stableswap_a, admin):
    with boa.env.prank(admin):
        crypto_agg = boa.load(
                'contracts/price_oracles/CryptoWithStablePrice.vy',
                dummy_tricrypto.address, 0,
                stableswap_a, agg, 5000)
        crypto_agg.price_w()
        return crypto_agg


@pytest.fixture(scope="module")
def peg_keepers(stablecoin_a, stablecoin_b, stableswap_a, stableswap_b, controller_factory, agg, admin):
    pks = []
    with boa.env.prank(admin):
        for (coin, pool) in [(stablecoin_a, stableswap_a), (stablecoin_b, stableswap_b)]:
            pks.append(
                    boa.load(
                        'contracts/stabilizer/PegKeeper.vy',
                        pool.address, 1, admin, 5 * 10**4,
                        controller_factory.address, agg.address)
            )
    return pks
