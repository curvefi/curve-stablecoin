import boa
import pytest


@pytest.fixture(scope="session")
def stablecoin_pre():
    return boa.load_partial('contracts/Stablecoin.vy')


@pytest.fixture(scope="module")
def stablecoin(stablecoin_pre, admin):
    with boa.env.prank(admin):
        return stablecoin_pre.deploy('Curve USD', 'crvUSD')


@pytest.fixture(scope="session")
def weth(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/WETH.vy')


@pytest.fixture(scope="session")
def controller_factory_impl():
    return boa.load_partial('contracts/ControllerFactory.vy')


@pytest.fixture(scope="module")
def controller_prefactory(controller_factory_impl, stablecoin, weth, admin, accounts):
    with boa.env.prank(admin):
        return controller_factory_impl.deploy(stablecoin.address, admin, accounts[0], weth.address)


@pytest.fixture(scope="session")
def controller_interface():
    return boa.load_partial('contracts/flashloan/FlashLender.vy')


@pytest.fixture(scope="session")
def controller_impl(controller_interface, admin):
    with boa.env.prank(admin):
        return controller_interface.deploy_as_blueprint()


@pytest.fixture(scope="session")
def amm_interface():
    return boa.load_partial('contracts/AMM.vy')


@pytest.fixture(scope="session")
def amm_impl(amm_interface, admin):
    with boa.env.prank(admin):
        return amm_interface.deploy_as_blueprint()


@pytest.fixture(scope="module")
def controller_factory(controller_prefactory, amm_impl, controller_impl, stablecoin, admin):
    with boa.env.prank(admin):
        controller_prefactory.set_implementations(controller_impl.address, amm_impl.address)
        stablecoin.set_minter(controller_prefactory.address)
    return controller_prefactory


@pytest.fixture(scope="module")
def flash_lender(controller_factory, admin):
    with boa.env.prank(admin):
        fl = boa.load('contracts/flashloan/FlashLender.vy', controller_factory.address)
        controller_factory.set_debt_ceiling(fl.address, 3 * 10**6 * 10 ** 18)

        return fl
