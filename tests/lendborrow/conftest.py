import pytest


@pytest.fixture(scope="module", autouse=True)
def stablecoin(Stablecoin, accounts):
    return Stablecoin.deploy('Curve USD', 'crvUSD', {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def controller_prefactory(ControllerFactory, stablecoin, accounts):
    return ControllerFactory.deploy(stablecoin, accounts[0], accounts[1], {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def controller_impl(Controller, controller_prefactory, accounts):
    return Controller.deploy(controller_prefactory, {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def amm_impl(AMM, controller_prefactory, stablecoin, accounts):
    return AMM.deploy(controller_prefactory, stablecoin, {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def controller_factory(controller_prefactory, amm_impl, controller_impl, stablecoin, accounts):
    controller_prefactory.set_implementations(controller_impl, amm_impl, {'from': accounts[0]})
    stablecoin.set_minter(controller_prefactory, True, {'from': accounts[0]})
    stablecoin.set_minter(accounts[0], False, {'from': accounts[0]})
    return controller_prefactory


@pytest.fixture(autouse=True)
def isolate(fn_isolation):
    pass
