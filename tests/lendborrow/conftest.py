import boa
import pytest
from vyper.utils import abi_method_id


def get_method_id(desc):
    return abi_method_id(desc).to_bytes(4, 'big') + b'\x00' * 28


@pytest.fixture(scope="module")
def stablecoin(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/Stablecoin.vy', 'Curve USD', 'crvUSD')


@pytest.fixture(scope="module")
def weth(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/WETH.vy')


@pytest.fixture(scope="module")
def controller_prefactory(stablecoin, weth, admin, accounts):
    with boa.env.prank(admin):
        return boa.load('contracts/ControllerFactory.vy', stablecoin.address, admin, accounts[0], weth.address)


@pytest.fixture(scope="module")
def controller_interface():
    return boa.load_partial('contracts/Controller.vy')


@pytest.fixture(scope="module")
def controller_impl(controller_prefactory, controller_interface, admin):
    with boa.env.prank(admin):
        return controller_interface.deploy_as_blueprint()


@pytest.fixture(scope="module")
def amm_interface():
    return boa.load_partial('contracts/AMM.vy')


@pytest.fixture(scope="module")
def amm_impl(stablecoin, amm_interface, admin):
    with boa.env.prank(admin):
        return amm_interface.deploy_as_blueprint()


@pytest.fixture(scope="module")
def controller_factory(controller_prefactory, amm_impl, controller_impl, stablecoin, admin):
    with boa.env.prank(admin):
        controller_prefactory.set_implementations(controller_impl.address, amm_impl.address)
        stablecoin.set_minter(controller_prefactory.address)
    return controller_prefactory


@pytest.fixture(scope="module")
def monetary_policy(admin):
    with boa.env.prank(admin):
        policy = boa.load('contracts/testing/ConstantMonetaryPolicy.vy', admin)
        policy.set_rate(0)
        return policy


@pytest.fixture(scope="module")
def market(controller_factory, collateral_token, monetary_policy, price_oracle, admin):
    with boa.env.prank(admin):
        if controller_factory.n_collaterals() == 0:
            controller_factory.add_market(
                collateral_token.address, 100, 10**16, 0,
                price_oracle.address,
                monetary_policy.address, 5 * 10**16, 2 * 10**16,
                10**6 * 10**18)
        return controller_factory


@pytest.fixture(scope="module")
def market_amm(market, collateral_token, stablecoin, amm_impl, amm_interface, accounts):
    amm = amm_interface.at(market.get_amm(collateral_token.address))
    for acc in accounts:
        with boa.env.prank(acc):
            collateral_token.approve(amm.address, 2**256-1)
            stablecoin.approve(amm.address, 2**256-1)
    return amm


@pytest.fixture(scope="module")
def market_controller(market, stablecoin, collateral_token, controller_impl, controller_interface, controller_factory, accounts):
    controller = controller_interface.at(market.get_controller(collateral_token.address))
    for acc in accounts:
        with boa.env.prank(acc):
            collateral_token.approve(controller.address, 2**256-1)
            stablecoin.approve(controller.address, 2**256-1)
    return controller


@pytest.fixture(scope="module")
def fake_leverage(stablecoin, collateral_token, market_controller, admin):
    # Fake leverage testing contract can also be used to liquidate via the callback
    with boa.env.prank(admin):
        leverage = boa.load('contracts/testing/FakeLeverage.vy', stablecoin.address, collateral_token.address,
                            market_controller.address, 3000 * 10**18)
        collateral_token._mint_for_testing(leverage.address, 1000 * 10**18)
        return leverage
