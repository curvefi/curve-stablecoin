import boa
import pytest
from boa.contract import VyperContract

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


@pytest.fixture(scope="session")
def swap_impl(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/Stableswap.vy')


@pytest.fixture(scope="session")
def swap_deployer(swap_impl, admin):
    with boa.env.prank(admin):
        deployer = boa.load('contracts/testing/SwapFactory.vy', swap_impl.address)
        return deployer


@pytest.fixture(scope="module")
def redeemable_coin(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "Unbranded Redeemable USD", "urUSD", 6)


@pytest.fixture(scope="module")
def volatile_coin(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "Volatile USD", "vUSD", 18)


@pytest.fixture(scope="module")
def swap(swap_deployer, swap_impl, redeemable_coin, volatile_coin, admin):
    with boa.env.prank(admin):
        n = swap_deployer.n()
        swap_deployer.deploy(redeemable_coin, volatile_coin)
        addr = swap_deployer.pools(n)
        return VyperContract(
            swap_impl.compiler_data,
            override_address=addr
        )
