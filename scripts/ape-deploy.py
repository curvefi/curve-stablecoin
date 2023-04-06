from ape import project, accounts, Contract
from ape.cli import NetworkBoundCommand, network_option
# account_option could be used when in prod?
import click

SHORT_NAME = "crvUSD"
FULL_NAME = "Curve.Fi USD Stablecoin"

rtokens = {
    # "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    # "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDP": "0x8E870D67F660D95d5be530380D0eC0bd388289E1",
    "TUSD": "0x0000000000085d4780B73119b644AE5ecd22b376",
}

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
POOL_NAME = "crvUSD/{name}"
POOL_SYMBOL = "crvUSD{name}"

A = 200  # initially, can go higher later
fee = 4000000  # 0.04%
asset_type = 0
implementation_idx = 4
ma_exp_time = 866  # 10 min / ln(2)


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
    tx = account.sign_transaction(tx)
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
    # Deployer address
    if ':local:' in network or ':mainnet-fork:' in network:
        account = accounts.test_accounts[0]
    elif ':mainnet:' in network:
        account = accounts.load('babe')

    temporary_admin = account

    # Admin and fee receiver <- DAO if in prod or mainnet-fork
    if ':local:' in network:
        admin = account
        fee_receiver = account
    elif 'mainnet' in network:
        admin = '0x40907540d8a6C65c637785e8f8B742ae6b0b9968'  # Ownership admin
        fee_receiver = '0xeCb456EA5365865EbAb8a2661B0c503410e9B347'  # 0xECB for fee collection

    # Real or fake wETH
    if ':local:' in network:
        weth = account.deploy(project.WETH)
    elif 'mainnet' in network:
        weth = Contract("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")

    with accounts.use_sender(account):
        # Common deployment steps - stablecoin, factory and implementations
        print("Deploying stablecoin")
        stablecoin = account.deploy(project.Stablecoin, FULL_NAME, SHORT_NAME)
        print("Deploying factory")
        factory = account.deploy(project.ControllerFactory, stablecoin, temporary_admin, weth, fee_receiver)

        print("Deploying Controller and AMM implementations")
        controller_impl = deploy_blueprint(project.Controller, account)
        amm_impl = deploy_blueprint(project.AMM, account)

        print("Setting implementations in the factory")
        factory.set_implementations(controller_impl, amm_impl)
        stablecoin.set_minter(factory)

        # Deploy plain pools and stabilizer
        if 'mainnet' in network:
            pool_deployer = Contract("0x742C3cF9Af45f91B109a81EfEaf11535ECDe9571")

            for name, rtoken in rtokens.items():
                print(f"Deploying a stablecoin pool with {name} ({rtoken})")
                tx = pool_deployer.deploy_plain_pool(
                    POOL_NAME.format(name=name),
                    POOL_SYMBOL.format(name=name),
                    [rtoken, stablecoin.address, ZERO_ADDRESS, ZERO_ADDRESS],
                    A,
                    fee,
                    asset_type,
                    implementation_idx,
                    ma_exp_time)
                # This is a workaround: instead of getting return_value we parse events to get the pool address
                # This is because reading return_value in ape is broken
                # Another workaround is manual filtering by contract_address
                # This is because reading events filtered by contract address in ape is broken
                pool = project.Stableswap.at([
                        e for e in tx.events.filter(stablecoin.Approval)
                        if e.contract_address == stablecoin.address
                    ][0]._spender)
                print(f"Stablecoin pool crvUSD/{name} is deployed at {pool.address}")

        if 'mainnet-fork' in network or 'local' in network:
            policy = account.deploy(project.ConstantMonetaryPolicy, temporary_admin)
            policy.set_rate(0)  # 0%
            price_oracle = account.deploy(project.DummyPriceOracle, admin, 3000 * 10**18)

        factory.add_market(
            weth, 100, 10**16, 0,
            price_oracle,
            policy, 5 * 10**16, 2 * 10**16,
            10**6 * 10**18
        )

        if admin != temporary_admin:
            policy.set_admin(admin)
            factory.set_admin(admin)

    amm = project.AMM.at(factory.get_amm(weth))
    controller = project.Controller.at(factory.get_controller(weth))

    print('========================')
    print('Stablecoin:        ', stablecoin.address)
    print('Factory:           ', factory.address)
    print('Collateral (WETH): ', weth.address)
    print('AMM:               ', amm.address)
    print('Controller:        ', controller.address)
    print('Price Oracle:      ', price_oracle.address)
    print('Monetary policy:   ', policy.address)
