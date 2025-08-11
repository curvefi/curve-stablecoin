import boa
import pytest
from boa.interpret import VyperContract
from tests.utils.deployers import (
    STABLESWAP_DEPLOYER,
    SWAP_FACTORY_DEPLOYER,
    ERC20_MOCK_DEPLOYER
)
from tests.utils.constants import ZERO_ADDRESS


@pytest.fixture(scope="session")
def swap_impl(admin):
    with boa.env.prank(admin):
        return STABLESWAP_DEPLOYER.deploy()


@pytest.fixture(scope="session")
def swap_deployer(swap_impl, admin):
    with boa.env.prank(admin):
        deployer = SWAP_FACTORY_DEPLOYER.deploy(swap_impl.address)
        return deployer


@pytest.fixture(scope="session")
def redeemable_coin(admin):
    with boa.env.prank(admin):
        return ERC20_MOCK_DEPLOYER.deploy("Unbranded Redeemable USD", "urUSD", 6)


@pytest.fixture(scope="session")
def volatile_coin(admin):
    with boa.env.prank(admin):
        return ERC20_MOCK_DEPLOYER.deploy("Volatile USD", "vUSD", 18)


@pytest.fixture(scope="session")
def swap(swap_deployer, swap_impl, redeemable_coin, volatile_coin, admin):
    with boa.env.prank(admin):
        n = swap_deployer.n()
        swap_deployer.deploy(redeemable_coin, volatile_coin)
        addr = swap_deployer.pools(n)
        swap = VyperContract(
            swap_impl.compiler_data,
            override_address=addr
        )
        return swap


@pytest.fixture(scope="session")
def swap_w_d(swap, redeemable_coin, volatile_coin, accounts, admin):
    with boa.env.prank(admin):
        redeemable_coin._mint_for_testing(admin, 10**6 * 10**6)
        volatile_coin._mint_for_testing(admin, 10**6 * 10**18)
        redeemable_coin.approve(swap.address, 2**256 - 1)
        volatile_coin.approve(swap.address, 2**256 - 1)
        swap.add_liquidity([10**6 * 10**6, 10**6 * 10**18], 0)
    for acc in accounts:
        with boa.env.prank(acc):
            redeemable_coin.approve(swap.address, 2**256 - 1)
            volatile_coin.approve(swap.address, 2**256 - 1)
    return swap
