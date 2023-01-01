from ape import project, accounts
from ape.cli import NetworkBoundCommand, network_option
# account_option could be used when in prod?
import click

SHORT_NAME = "crvUSD"
FULL_NAME = "Curve.Fi USD Stablecoin"


def deploy_blueprint(contract, account):
    initcode = contract.contract_type.deployment_bytecode.bytecode
    if isinstance(initcode, str):
        initcode = bytes.fromhex(initcode.removeprefix("0x"))
    initcode = b"\xfe\x71\x00" + initcode  # eip-5202 preamble version 0
    initcode = (
        b"\x61" + len(initcode).to_bytes(2, "big") + b"\x3d\x81\x60\x0a\x3d\x39\xf3" + initcode
    )
    tx = project.provider.network.ecosystem.create_transaction(
        chain_id=project.provider.chain_id,
        data=initcode,
        gas_price=project.provider.gas_price,
        nonce=account.nonce,
    )
    tx.gas_limit = project.provider.estimate_gas_cost(tx)
    tx.signature = account.sign_transaction(tx)
    receipt = project.provider.send_transaction(tx)
    click.echo(f"blueprint deployed at: {receipt.contract_address}")
    return receipt.contract_address


@click.group()
def cli():
    """
    Script for test deployment of crvUSD
    """


@cli.command(
    cls=NetworkBoundCommand,
)
@network_option()
def deploy(network):
    if 'hardhat' not in network and 'foundry' not in network:
        # admin = fee_receiver = accounts.load('babe')
        raise NotImplementedError("Mainnet not implemented yet")
    else:
        account = accounts.test_accounts[0]
        admin = account
        fee_receiver = account
        weth = account.deploy(project.WETH)

    stablecoin = account.deploy(project.Stablecoin, FULL_NAME, SHORT_NAME)
    factory = account.deploy(project.ControllerFactory, stablecoin, admin, weth, fee_receiver)

    controller_impl = deploy_blueprint(project.Controller, account)
    amm_impl = deploy_blueprint(project.AMM, account)

    factory.set_implementations(controller_impl, amm_impl, sender=account)
    stablecoin.set_minter(factory.address, sender=account)

    if 'hardhat' in network or 'foundry' in network:
        policy = account.deploy(project.ConstantMonetaryPolicy, admin)
        policy.set_rate(0, sender=account)  # 0%
        price_oracle = account.deploy(project.DummyPriceOracle, admin, 3000 * 10**18)

    factory.add_market(
        weth, 100, 10**16, 0,
        price_oracle,
        policy, 5 * 10**16, 2 * 10**16,
        10**6 * 10**18,
        sender=account
    )

    amm = project.AMM.at(factory.get_amm(weth))
    controller = project.Controller.at(factory.get_controller(weth))

    print('========================')
    print('Stablecoin:        ', stablecoin.address)
    print('Factory:           ', factory.address)
    print('Collateral (WETH): ', weth.address)
    print('AMM:               ', amm.address)
    print('Controller:        ', controller.address)
