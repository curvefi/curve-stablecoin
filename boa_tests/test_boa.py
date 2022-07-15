import boa
import pytest

# Patch EIP170 size limit because spurious dragon does the wrong code size
from eth.vm.forks.spurious_dragon import computation
computation.EIP170_CODE_SIZE_LIMIT = 640000  # 640 KB will be enough for everyone


PRICE = 3000


@pytest.fixture(scope="module", autouse=True)
def accounts():
    return [boa.env.generate_address() for i in range(10)]


@pytest.fixture(scope="module", autouse=True)
def admin():
    return boa.env.generate_address()


@pytest.fixture(scope="module", autouse=True)
def stablecoin(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/Stablecoin.vy', 'Curve USD', 'crvUSD')


@pytest.fixture(scope="module", autouse=True)
def collateral_token(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "Colalteral", "ETH", 18)


@pytest.fixture(scope="module", autouse=True)
def controller_prefactory(stablecoin, admin, accounts):
    with boa.env.prank(admin):
        return boa.load('contracts/ControllerFactory.vy', stablecoin.address, admin, accounts[0])


@pytest.fixture(scope="module", autouse=True)
def controller_impl(controller_prefactory, admin):
    with boa.env.prank(admin):
        return boa.load('contracts/Controller.vy', controller_prefactory.address)


@pytest.fixture(scope="module", autouse=True)
def amm_impl(stablecoin, admin):
    with boa.env.prank(admin):
        return boa.load('contracts/AMM.vy', stablecoin.address)


@pytest.fixture(scope="module", autouse=True)
def controller_factory(controller_prefactory, amm_impl, controller_impl, stablecoin, admin):
    with boa.env.prank(admin):
        controller_prefactory.set_implementations(controller_impl.address, amm_impl.address)
        stablecoin.set_minter(controller_prefactory.address, True)
        stablecoin.set_minter(admin, False)
    return controller_prefactory


@pytest.fixture(scope="module", autouse=True)
def monetary_policy(admin):
    with boa.env.prank(admin):
        policy = boa.load('contracts/mpolicies/ConstantMonetaryPolicy.vy', admin)
        policy.set_rate(0)
        return policy


@pytest.fixture(scope="module", autouse=True)
def price_oracle(admin):
    with boa.env.prank(admin):
        oracle = boa.load('contracts/testing/DummyPriceOracle.vy', admin, PRICE * 10**18)
        return oracle


@pytest.fixture(scope="module", autouse=True)
def market(controller_factory, collateral_token, monetary_policy, price_oracle, admin):
    with boa.env.prank(admin):
        if controller_factory.n_collaterals() == 0:
            controller_factory.add_market(
                collateral_token.address, 100, 10**16, 0,
                price_oracle.address,
                monetary_policy.address, 5 * 10**16, 2 * 10**16,
                10**6 * 10**18)
        return controller_factory


def test_stablecoin(stablecoin, collateral_token, market, amm_impl):
    assert stablecoin.decimals() == 18
    assert False
