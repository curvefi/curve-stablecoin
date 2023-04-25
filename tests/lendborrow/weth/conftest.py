import boa
import pytest


@pytest.fixture(scope="module")
def stablecoin(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/Stablecoin.vy', 'Curve USD', 'crvUSD')


@pytest.fixture(scope="module")
def controller_prefactory(stablecoin, weth, admin, accounts):
    with boa.env.prank(admin):
        return boa.load('contracts/ControllerFactory.vy', stablecoin.address, admin, accounts[0], weth.address)


@pytest.fixture(scope="module")
def controller_factory(controller_prefactory, amm_impl, controller_impl, stablecoin, admin):
    with boa.env.prank(admin):
        controller_prefactory.set_implementations(controller_impl.address, amm_impl.address)
        stablecoin.set_minter(controller_prefactory.address)
    return controller_prefactory


@pytest.fixture(scope="module")
def market(controller_factory, weth, monetary_policy, price_oracle, admin):
    with boa.env.prank(admin):
        if controller_factory.n_collaterals() == 0:
            controller_factory.add_market(
                weth.address, 100, 10**16, 0,
                price_oracle.address,
                monetary_policy.address, 5 * 10**16, 2 * 10**16,
                10**6 * 10**18)
        return controller_factory


@pytest.fixture(scope="module")
def market_amm(market, weth, stablecoin, amm_impl, amm_interface, accounts):
    amm = amm_interface.at(market.get_amm(weth.address))
    for acc in accounts:
        with boa.env.prank(acc):
            weth.approve(amm.address, 2**256-1)
            stablecoin.approve(amm.address, 2**256-1)
    return amm


@pytest.fixture(scope="module")
def market_controller(market, stablecoin, weth, controller_impl, controller_interface, controller_factory, accounts):
    controller = controller_interface.at(market.get_controller(weth.address))
    for acc in accounts:
        with boa.env.prank(acc):
            weth.approve(controller.address, 2**256-1)
            stablecoin.approve(controller.address, 2**256-1)
    return controller


@pytest.fixture(scope="module")
def fake_leverage(stablecoin, weth, market_controller, admin):
    # Fake leverage testing contract can also be used to liquidate via the callback
    with boa.env.prank(admin):
        leverage = boa.load('contracts/testing/FakeLeverage.vy', stablecoin.address, weth.address,
                            market_controller.address, 3000 * 10**18)
        c_amount = 1000 * 10**18
        boa.env.set_balance(admin, c_amount)
        weth.deposit(value=c_amount)
        weth.transfer(leverage.address, c_amount)
        return leverage
