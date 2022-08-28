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
