import boa
import pytest
from tests.utils.deployers import (
    STABLECOIN_DEPLOYER,
    WETH_DEPLOYER,
    CONTROLLER_FACTORY_DEPLOYER,
    FLASH_LENDER_DEPLOYER,
    AMM_DEPLOYER,
    DUMMY_FLASH_BORROWER_DEPLOYER
)


@pytest.fixture(scope="session")
def stablecoin_pre():
    return STABLECOIN_DEPLOYER


@pytest.fixture(scope="module")
def stablecoin(stablecoin_pre, admin):
    with boa.env.prank(admin):
        _stablecoin = stablecoin_pre.deploy('Curve USD', 'crvUSD')
        _stablecoin.mint(admin, 10**21)
        return _stablecoin


@pytest.fixture(scope="session")
def weth(admin):
    with boa.env.prank(admin):
        return WETH_DEPLOYER.deploy()


@pytest.fixture(scope="session")
def controller_factory_impl():
    return CONTROLLER_FACTORY_DEPLOYER


@pytest.fixture(scope="module")
def controller_prefactory(controller_factory_impl, stablecoin, weth, admin, accounts):
    with boa.env.prank(admin):
        return controller_factory_impl.deploy(stablecoin.address, admin, accounts[0], weth.address)


@pytest.fixture(scope="session")
def controller_interface():
    return FLASH_LENDER_DEPLOYER


@pytest.fixture(scope="session")
def controller_impl(controller_interface, admin):
    with boa.env.prank(admin):
        return controller_interface.deploy_as_blueprint()


@pytest.fixture(scope="session")
def amm_interface():
    return AMM_DEPLOYER


@pytest.fixture(scope="session")
def amm_impl(amm_interface, admin):
    with boa.env.prank(admin):
        return amm_interface.deploy_as_blueprint()


@pytest.fixture(scope="session")
def user():
    return boa.env.generate_address()


@pytest.fixture(scope="module")
def controller_factory(controller_prefactory, amm_impl, controller_impl, stablecoin, admin):
    with boa.env.prank(admin):
        controller_prefactory.set_implementations(controller_impl.address, amm_impl.address)
        stablecoin.set_minter(controller_prefactory.address)
    return controller_prefactory


@pytest.fixture(scope="module")
def max_flash_loan():
    return 3 * 10**6 * 10 ** 18


@pytest.fixture(scope="module")
def flash_lender(controller_factory, admin, max_flash_loan):
    with boa.env.prank(admin):
        fl = FLASH_LENDER_DEPLOYER.deploy(controller_factory.address)
        controller_factory.set_debt_ceiling(fl.address, max_flash_loan)

        return fl


@pytest.fixture(scope="module")
def flash_borrower(flash_lender, admin):
    with boa.env.prank(admin):
        return DUMMY_FLASH_BORROWER_DEPLOYER.deploy(flash_lender.address)
