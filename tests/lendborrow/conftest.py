import pytest


def deploy_blueprint(contract, account, txparams={}):
    bytecode = b"\xFE\x71\x00" + bytes.fromhex(contract.bytecode[2:])
    bytecode = b"\x61" + len(bytecode).to_bytes(2, "big") + b"\x3d\x81\x60\x0a\x3d\x39\xf3" + bytecode
    tx = account.transfer(data=bytecode, **txparams)
    return tx.contract_address


@pytest.fixture(scope="module", autouse=True)
def stablecoin(Stablecoin, accounts):
    return Stablecoin.deploy('Curve USD', 'crvUSD', {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def controller_prefactory(ControllerFactory, stablecoin, accounts):
    return ControllerFactory.deploy(stablecoin, accounts[0], accounts[1], {'from': accounts[0]})


@pytest.fixture(scope="module", autouse=True)
def controller_impl(Controller, controller_prefactory, accounts):
    return deploy_blueprint(Controller, accounts[0])


@pytest.fixture(scope="module", autouse=True)
def amm_impl(AMM, stablecoin, accounts):
    return deploy_blueprint(AMM, accounts[0])


@pytest.fixture(scope="module", autouse=True)
def controller_factory(controller_prefactory, amm_impl, controller_impl, stablecoin, accounts):
    controller_prefactory.set_implementations(controller_impl, amm_impl, {'from': accounts[0]})
    stablecoin.set_minter(controller_prefactory, True, {'from': accounts[0]})
    stablecoin.set_minter(accounts[0], False, {'from': accounts[0]})
    return controller_prefactory


@pytest.fixture(scope="module", autouse=True)
def monetary_policy(ConstantMonetaryPolicy, accounts):
    policy = ConstantMonetaryPolicy.deploy(accounts[0], {'from': accounts[0]})
    # policy.set_rate(int(1e18 * 0.04 / 365 / 86400), {'from': accounts[0]})  # 4%
    policy.set_rate(0, {'from': accounts[0]})  # 0%
    return policy


@pytest.fixture(scope="module", autouse=False)
def market(controller_factory, collateral_token, PriceOracle, monetary_policy, accounts):
    if controller_factory.n_collaterals() == 0:
        controller_factory.add_market(
            collateral_token, 100, 10**16, 0,
            PriceOracle,
            monetary_policy, 5 * 10**16, 2 * 10**16,
            10**6 * 10**18,
            {'from': accounts[0]})
    return controller_factory


@pytest.fixture(scope="module", autouse=False)
def market_amm(collateral_token, stablecoin, market, AMM, accounts):
    amm = AMM.at(market.amms(collateral_token))
    for acc in accounts:
        collateral_token.approve(amm, 2**256-1, {'from': acc})
        stablecoin.approve(amm, 2**256-1, {'from': acc})
    return amm


@pytest.fixture(scope="module", autouse=False)
def market_controller(stablecoin, collateral_token, market, Controller, accounts):
    controller = Controller.at(market.controllers(collateral_token))
    for acc in accounts:
        collateral_token.approve(controller, 2**256-1, {'from': acc})
        stablecoin.approve(controller, 2**256-1, {'from': acc})
    return controller


@pytest.fixture(autouse=True)
def isolate(fn_isolation):
    pass
