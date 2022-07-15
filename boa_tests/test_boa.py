import boa
import pytest


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


def test_stablecoin(stablecoin, controller_impl):
    assert stablecoin.decimals() == 18
