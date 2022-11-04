from brownie import accounts, network
from brownie import ControllerFactory, Controller, AMM, Stablecoin
from brownie import ConstantMonetaryPolicy, DummyPriceOracle
from brownie import ERC20Mock

SHORT_NAME = "crvUSD"
FULL_NAME = "Curve.Fi USD Stablecoin"


def deploy_blueprint(contract, account, txparams={}):
    txparams = {k: v for k, v in txparams.items() if k != 'from'}
    bytecode = b"\xFE\x71\x00" + bytes.fromhex(contract.bytecode[2:])
    bytecode = b"\x61" + len(bytecode).to_bytes(2, "big") + b"\x3d\x81\x60\x0a\x3d\x39\xf3" + bytecode
    tx = account.transfer(data=bytecode, **txparams)
    return tx.contract_address


def main():
    mainnet = network.show_active() == 'mainnet'
    if mainnet:
        raise NotImplementedError("Mainnet not implemented yet")
    else:
        txparams = {'from': accounts[0]}
        admin = accounts[0]
        fee_receiver = accounts[0]

    stablecoin = Stablecoin.deploy(FULL_NAME, SHORT_NAME, txparams)
    factory = ControllerFactory.deploy(stablecoin, admin, fee_receiver, txparams)
    controller_impl = deploy_blueprint(Controller, accounts[0], txparams)
    amm_impl = deploy_blueprint(AMM, accounts[0], txparams)

    factory.set_implementations(controller_impl, amm_impl, txparams)
    stablecoin.set_minter(factory, txparams)

    if not mainnet:
        policy = ConstantMonetaryPolicy.deploy(admin, txparams)
        policy.set_rate(0, txparams)  # 0%
        price_oracle = DummyPriceOracle.deploy(admin, 3000 * 10**18, txparams)
        collateral_token = ERC20Mock.deploy('Collateral WETH', 'WETH', 18, txparams)

    factory.add_market(
        collateral_token, 100, 10**16, 0,
        price_oracle,
        policy, 5 * 10**16, 2 * 10**16,
        10**6 * 10**18,
        txparams)

    amm = AMM.at(factory.get_amm(collateral_token))
    controller = Controller.at(factory.get_controller(collateral_token))

    if not mainnet:
        for user in accounts:
            collateral_token._mint_for_testing(user, 10**4 * 10**18, txparams)

    print('========================')
    print('Stablecoin:  ', stablecoin.address)
    print('Factory:     ', factory.address)
    print('Collateral:  ', collateral_token.address)
    print('AMM:         ', amm.address)
    print('Controller:  ', controller.address)
