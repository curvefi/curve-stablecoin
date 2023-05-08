from ape import project, accounts, Contract, networks
from ape.cli import NetworkBoundCommand, network_option
# account_option could be used when in prod?
import click

from dotenv import load_dotenv
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))

SHORT_NAME = "crvUSD"
FULL_NAME = "Curve.Fi USD Stablecoin"

rtokens = {
    "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    "USDP": "0x8E870D67F660D95d5be530380D0eC0bd388289E1",
    "TUSD": "0x0000000000085d4780B73119b644AE5ecd22b376",
}

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
POOL_NAME = "crvUSD/{name}"
POOL_SYMBOL = "crvUSD{name}"

OWNERSHIP_ADMIN = "0x40907540d8a6C65c637785e8f8B742ae6b0b9968"
PARAMETER_ADMIN = "0x4EEb3bA4f221cA16ed4A0cC7254E2E32DF948c5f"
EMERGENCY_ADMIN = "0x467947EE34aF926cF1DCac093870f613C96B1E0c"

GAUGE_IMPL = "0x5aE854b098727a9f1603A1E21c50D52DC834D846"
ADDRESS_PROVIDER = "0x0000000022D53366457F9d5E68Ec105046FC4383"
SET_ADDRESS_PROVIDER = False
STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID = 8
FEE_RECEIVER = "0xeCb456EA5365865EbAb8a2661B0c503410e9B347"

WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"

TRICRYPTO = "0xD51a44d3FaE010294C616388b506AcdA1bfAAE46"

CHAINLINK_ETH = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"

FRXETH_POOL = "0xa1f8a6807c402e4a15ef4eba36528a3fed24e577"
SFRXETH = "0xac3E018457B222d93114458476f3E3416Abbe38F"

stable_A = 500  # initially, can go higher later
stable_fee = 1000000  # 0.01%
stable_asset_type = 0
stable_ma_exp_time = 866  # 10 min / ln(2)

policy_rate = 627954226  # 2%
policy_sigma = 2 * 10**16  # 2% when at target debt fraction
policy_debt_fraction = 5 * 10**16  # 5%

oracle_bound_size = 1  # %
oracle_ema = 600  # s

market_A = 100
market_fee = 3 * 10**15  # 0.3%
market_admin_fee = 0
market_loan_discount = 9 * 10**16  # 9%; +2% from 4x 1% bands = 100% - 11% = 89% LTV
market_liquidation_discount = 6 * 10**16  # 6%
market_debt_ceiling = 10**7 * 10**18  # 10M
initial_pk_funds = market_debt_ceiling // len(rtokens)


def deploy_blueprint(contract, account, **kw):
    initcode = contract.contract_type.deployment_bytecode.bytecode
    if isinstance(initcode, str):
        initcode = bytes.fromhex(initcode.removeprefix("0x"))
    initcode = b"\xfe\x71\x00" + initcode  # eip-5202 preamble version 0
    initcode = (
        b"\x61" + len(initcode).to_bytes(2, "big") + b"\x3d\x81\x60\x0a\x3d\x39\xf3" + initcode
    )
    if not kw:
        kw = {'gas_price': project.provider.gas_price}
    tx = project.provider.network.ecosystem.create_transaction(
        chain_id=project.provider.chain_id,
        data=initcode,
        nonce=account.nonce,
        **kw
    )
    receipt = account.call(tx)
    click.echo(f"blueprint deployed at: {receipt.contract_address}")
    return receipt.contract_address


@click.group()
def cli():
    """
    Script for production deployment of crvUSD
    """


@cli.command(
    cls=NetworkBoundCommand,
)
@network_option()
def deploy(network):
    kw = {}

    # Deployer address
    if ':local:' in network:
        account = accounts.test_accounts[0]
    elif ':mainnet:' in network:
        account = accounts.load('babe')
        account.set_autosign(True)
        max_base_fee = networks.active_provider.base_fee * 2
        kw = {
            'max_fee': max_base_fee,
            'max_priority_fee': min(int(0.5e9), max_base_fee)}
    else:
        account = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
        if account in accounts:
            account = accounts.load('babe')
            account.set_autosign(True)

    temporary_admin = account

    # Admin and fee receiver <- DAO if in prod or mainnet-fork
    if 'mainnet' in network:
        admin = OWNERSHIP_ADMIN  # Ownership admin
        fee_receiver = FEE_RECEIVER  # 0xECB for fee collection
    else:
        admin = account
        fee_receiver = account

    with accounts.use_sender(account) as account:
        # Real or fake wETH
        if 'mainnet' in network:
            weth = Contract(WETH)
            collateral = SFRXETH
        else:
            weth = account.deploy(project.WETH)
            collateral = weth

        # Common deployment steps - stablecoin, factory and implementations
        print("Deploying stablecoin")
        stablecoin = account.deploy(project.Stablecoin, FULL_NAME, SHORT_NAME, **kw)
        print("Deploying factory")
        factory = account.deploy(project.ControllerFactory, stablecoin, temporary_admin, fee_receiver, weth, **kw)

        print("Deploying Controller and AMM implementations")
        controller_impl = deploy_blueprint(project.Controller, account, **kw)
        amm_impl = deploy_blueprint(project.AMM, account, **kw)

        print("Setting implementations in the factory")
        factory.set_implementations(controller_impl, amm_impl, **kw)
        stablecoin.set_minter(factory, **kw)

        # Deploy plain pools and stabilizer
        if 'mainnet' in network:
            swap_factory = account.deploy(project.StableswapFactory, FEE_RECEIVER, **kw)
            swap_factory.add_token_to_whitelist(stablecoin, True, **kw)

            # Ownership admin is account temporarily, will need to become OWNERSHIP_ADMIN
            owner_proxy = account.deploy(project.OwnerProxy,
                                         temporary_admin, PARAMETER_ADMIN, EMERGENCY_ADMIN,
                                         swap_factory, ZERO_ADDRESS, **kw)
            swap_factory.commit_transfer_ownership(owner_proxy, **kw)
            owner_proxy.accept_transfer_ownership(swap_factory, **kw)

            # Set implementations
            stableswap_impl = account.deploy(project.Stableswap, **kw)
            owner_proxy.set_plain_implementations(swap_factory, 2, [stableswap_impl.address] + [ZERO_ADDRESS] * 9, **kw)
            owner_proxy.set_gauge_implementation(swap_factory, GAUGE_IMPL, **kw)

            # Set all admins to the DAO
            owner_proxy.commit_set_admins(OWNERSHIP_ADMIN, PARAMETER_ADMIN, EMERGENCY_ADMIN, **kw)
            owner_proxy.apply_set_admins(**kw)

            if SET_ADDRESS_PROVIDER:
                # Put factory in address provider / registry
                address_provider = Contract(ADDRESS_PROVIDER)
                address_provider_admin = Contract(address_provider.admin())

                if address_provider.get_address(STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID) == ZERO_ADDRESS:
                    address_provider_admin.execute(
                            address_provider,
                            address_provider.add_new_id.encode_input(swap_factory, 'crvUSD plain pools'),
                            **kw
                    )

                else:
                    address_provider_admin.execute(
                        address_provider,
                        address_provider.set_address.encode_input(
                            STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID,
                            swap_factory,
                            **kw
                        ),
                    )

            pools = {}

            # Deploy pools
            for name, rtoken in rtokens.items():
                print(f"Deploying a stablecoin pool with {name} ({rtoken})")
                tx = owner_proxy.deploy_plain_pool(
                    POOL_NAME.format(name=name),
                    POOL_SYMBOL.format(name=name),
                    [rtoken, stablecoin.address, ZERO_ADDRESS, ZERO_ADDRESS],
                    stable_A,
                    stable_fee,
                    stable_asset_type,
                    0,  # implentation_idx
                    stable_ma_exp_time,
                    **kw)
                # This is a workaround: instead of getting return_value we parse events to get the pool address
                # This is because reading return_value in ape is broken
                pool = project.Stableswap.at(tx.events.filter(swap_factory.PlainPoolDeployed)[0].pool)
                print(f"Stablecoin pool crvUSD/{name} is deployed at {pool.address}")
                pools[name] = pool

            # Price aggregator
            print("Deploying stable price aggregator")
            agg = account.deploy(project.AggregateStablePrice, stablecoin, 10**15, temporary_admin, **kw)
            for pool in pools.values():
                agg.add_price_pair(pool, **kw)
            agg.set_admin(admin, **kw)  # Alternatively, we can make it ZERO_ADDRESS

            # PegKeepers
            peg_keepers = []
            for pool in pools.values():
                print(f"Deploying a PegKeeper for {pool.name()}")
                peg_keeper = account.deploy(project.PegKeeper, pool, 1, FEE_RECEIVER, 2 * 10**4, factory, agg,
                                            admin, **kw)
                peg_keepers.append(peg_keeper)
                factory.set_debt_ceiling(peg_keeper, initial_pk_funds, **kw)

        if 'mainnet' in network:
            policy = account.deploy(project.AggMonetaryPolicy, admin, agg, factory,
                                    peg_keepers + [ZERO_ADDRESS],
                                    policy_rate, policy_sigma, policy_debt_fraction,
                                    **kw)

            # Pure ETH
            # price_oracle = account.deploy(
            #     project.CryptoWithStablePriceAndChainlink,
            #     TRICRYPTO,
            #     1,  # price index with ETH
            #     pools['USDT'],  # tricrypto is vs USDT
            #     agg,
            #     CHAINLINK_ETH,
            #     oracle_ema,
            #     oracle_bound_size)

            # sFrxETH
            price_oracle = account.deploy(
                    project.CryptoWithStablePriceAndChainlinkFrxeth,
                    TRICRYPTO,  # Tricrypto
                    1,  # price index with ETH
                    pools["USDT"],
                    FRXETH_POOL,  # staked swap (frxeth/eth)
                    agg,
                    CHAINLINK_ETH,  # ETH/USD Chainlink aggregator
                    SFRXETH,  # sFrxETH
                    600,
                    1,  # 1% bound
                    **kw)

            price_oracle.price_w(**kw)

            print('Price oracle price: {:.2f}'.format(price_oracle.price() / 1e18))

        else:
            policy = account.deploy(project.ConstantMonetaryPolicy, temporary_admin)
            policy.set_rate(0)  # 0%
            policy.set_admin(admin)
            price_oracle = account.deploy(project.DummyPriceOracle, admin, 3000 * 10**18)

        factory.add_market(
            collateral, market_A, market_fee, market_admin_fee,
            price_oracle, policy,
            market_loan_discount, market_liquidation_discount,
            market_debt_ceiling,
            **kw
        )

        if admin != temporary_admin:
            factory.set_admin(admin, **kw)

    amm = project.AMM.at(factory.get_amm(collateral))
    controller = project.Controller.at(factory.get_controller(collateral))

    print('========================')
    print('Stablecoin:        ', stablecoin.address)
    print('Factory:           ', factory.address)
    print('Collateral:        ', collateral)
    print('AMM:               ', amm.address)
    print('Controller:        ', controller.address)
    print('Price Oracle:      ', price_oracle.address)
    print('Monetary policy:   ', policy.address)
    if 'mainnet' in network:
        print('Swap factory:      ', swap_factory.address)
        print('Owner proxy:       ', owner_proxy.address)
        print('Price Aggregator:  ', agg.address)
        print('PegKeepers:        ', [pk.address for pk in peg_keepers])
        print('Stablecoin pools:  ', ['%s:%s' % (name, pool.address) for name, pool in pools.items()])
