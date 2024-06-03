from time import sleep
from ape import project, accounts, Contract
from ape.cli import NetworkBoundCommand, network_option
from ape import chain
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
    receipt = account.call(tx)
    click.echo(f"blueprint deployed at: {receipt.contract_address}")
    return receipt.contract_address

# ------------------------------------------------------------------------------------------

FRXETH = "0x5e8422345238f34275888049021821e8e08caa1f"
ROUTER = "0x99a58482bd75cbab83b27ec03ca68ff489b5788f"


def get_router_params(stablecoin, pools):
    return {
    'liquidation': {
        "usdc": {  # frxeth --> tricrypto2 --> 3pool --> crvUSD/USDC
            "route": [
                FRXETH,
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                pools["USDC"].address,
                stablecoin,
            ],
            "swap_params": [[1, 0, 1], [2, 0, 3], [2, 1, 1], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {  # frxeth --> tricrypto2 --> crvUSD/USDT
            "route": [
                FRXETH,
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                pools["USDT"].address,
                stablecoin,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [2, 0, 3], [0, 1, 1], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdp": {  # frxeth --> tricrypto2 --> factory-v2-59 --> crvUSD/USDP
            "route": [
                FRXETH,
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xc270b3b858c335b6ba5d5b10e2da8a09976005ad',
                '0x8e870d67f660d95d5be530380d0ec0bd388289e1',
                pools["USDP"].address,
                stablecoin,
            ],
            "swap_params": [[1, 0, 1], [2, 0, 3], [3, 0, 2], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000'
            ],
        },
        "tusd": {  # frxeth --> tricrypto2 --> tusd --> crvUSD/TUSD
            "route": [
                FRXETH,
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                pools["TUSD"].address,
                stablecoin,
            ],
            "swap_params": [[1, 0, 1], [2, 0, 3], [3, 0, 2], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    },

    # -----------------------------------------------------------------

    "deliquidation": {
        "usdc": {  # crvUSD/USDC --> 3pool --> tricrypto2 --> frxeth
            "route": [
                stablecoin,
                pools["USDC"],
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                FRXETH,
            ],
            "swap_params": [[1, 0, 1], [1, 2, 1], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {  # crvUSD/USDT --> tricrypto2 --> frxeth
            "route": [
                stablecoin,
                pools["USDT"],
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                FRXETH,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 2, 3], [0, 1, 1], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdp": {  # crvUSD/USDP --> factory-v2-59 -> tricrypto2 --> frxeth
            "route": [
                stablecoin,
                pools["USDP"],
                '0x8e870d67f660d95d5be530380d0ec0bd388289e1',
                '0xc270b3b858c335b6ba5d5b10e2da8a09976005ad',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                FRXETH,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {  # crvUSD/TUSD --> tusd -> tricrypto2 --> frxeth
            "route": [
                stablecoin,
                pools["TUSD"],
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                FRXETH,
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    },
}


@click.group()
def cli():
    """
    Script for test deployment of crvUSD
    """


@cli.command(
    cls=NetworkBoundCommand,
)
@network_option()
def test_liquidation(network):

    # ---------------- DEPLOY ----------------

    # Deployer address
    if ':local:' in network:
        account = accounts.test_accounts[0]
    elif ':mainnet-fork:' in network:
        account = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
        if account in accounts:
            account = accounts.load('babe')
            account.set_autosign(True)
    elif ':mainnet:' in network:
        account = accounts.load('babe')
        account.set_autosign(True)

    temporary_admin = account

    # Admin and fee receiver <- DAO if in prod or mainnet-fork
    if ':local:' in network:
        admin = account
        fee_receiver = account
    elif 'mainnet' in network:
        admin = OWNERSHIP_ADMIN  # Ownership admin
        fee_receiver = FEE_RECEIVER  # 0xECB for fee collection

    with accounts.use_sender(account) as account:
        # Real or fake wETH
        if ':local:' in network:
            weth = account.deploy(project.WETH)
            collateral = weth
        elif 'mainnet' in network:
            weth = Contract(WETH)
            collateral = SFRXETH

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
            swap_factory = account.deploy(project.StableswapFactory, FEE_RECEIVER)
            swap_factory.add_token_to_whitelist(stablecoin, True)

            # Ownership admin is account temporarily, will need to become OWNERSHIP_ADMIN
            owner_proxy = account.deploy(project.OwnerProxy,
                                         temporary_admin, PARAMETER_ADMIN, EMERGENCY_ADMIN,
                                         swap_factory, ZERO_ADDRESS)
            swap_factory.commit_transfer_ownership(owner_proxy)
            owner_proxy.accept_transfer_ownership(swap_factory)

            # Set implementations
            stableswap_impl = account.deploy(project.Stableswap)
            owner_proxy.set_plain_implementations(swap_factory, 2, [stableswap_impl.address] + [ZERO_ADDRESS] * 9)
            owner_proxy.set_gauge_implementation(swap_factory, GAUGE_IMPL)

            # Set all admins to the DAO
            owner_proxy.commit_set_admins(OWNERSHIP_ADMIN, PARAMETER_ADMIN, EMERGENCY_ADMIN)
            owner_proxy.apply_set_admins()

            # Put factory in address provider / registry
            address_provider = Contract(ADDRESS_PROVIDER)
            address_provider_admin = Contract(address_provider.admin())
            address_provider_admin.execute(
                    address_provider,
                    address_provider.add_new_id.encode_input(swap_factory, 'crvUSD plain pools'))

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
                    stable_ma_exp_time)
                # This is a workaround: instead of getting return_value we parse events to get the pool address
                # This is because reading return_value in ape is broken
                pool = project.Stableswap.at(tx.events.filter(swap_factory.PlainPoolDeployed)[0].pool)
                print(f"Stablecoin pool crvUSD/{name} is deployed at {pool.address}")
                pools[name] = pool

            # Price aggregator
            print("Deploying stable price aggregator")
            agg = account.deploy(project.AggregateStablePrice, stablecoin, 10**15, temporary_admin)
            for pool in pools.values():
                agg.add_price_pair(pool)
            agg.set_admin(admin)  # Alternatively, we can make it ZERO_ADDRESS

            # PegKeepers
            peg_keepers = []
            for pool in pools.values():
                print(f"Deploying a PegKeeper for {pool.name()}")
                peg_keeper = account.deploy(project.PegKeeper, pool, 1, FEE_RECEIVER, 2 * 10**4, factory, agg,
                                            admin)
                peg_keepers.append(peg_keeper)

        policy = account.deploy(project.ConstantMonetaryPolicy, temporary_admin)
        policy.set_rate(0)  # 0%
        policy.set_admin(admin)
        price_oracle = account.deploy(project.DummyPriceOracle, admin, 2000 * 10**18)

        factory.add_market(
            collateral, market_A, market_fee, market_admin_fee,
            price_oracle, policy,
            market_loan_discount, market_liquidation_discount,
            market_debt_ceiling
        )

        if admin != temporary_admin:
            factory.set_admin(admin)

    amm = project.AMM.at(factory.get_amm(collateral))
    controller = project.Controller.at(factory.get_controller(collateral))

    # --- ADD LIQUIDITY TO PEG POOLS ---

    # Steal tokens
    sfrxeth = Contract(SFRXETH)  # collateral
    sfrxeth.transfer(admin, 1000 * 10**18, sender="0x88441cCd7c41d4d6f4Edf7811C758065555226fA")
    project.ERC20Mock.at(rtokens["USDC"]).transfer(admin, 1_000_000 * 10**6, sender="0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503")  # Binance: Binance-Peg Tokens
    project.ERC20Mock.at(rtokens["USDT"]).transfer(admin, 1_000_000 * 10**6, sender="0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503")  # Binance: Binance-Peg Tokens
    project.ERC20Mock.at(rtokens["USDP"]).transfer(admin, 1_000_000 * 10**18, sender="0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503")  # Binance: Binance-Peg Tokens
    project.ERC20Mock.at(rtokens["TUSD"]).transfer(admin, 1_000_000 * 10**18, sender="0x47ac0Fb4F2D84898e4D9E7b4DaB3C24507a6D503")  # Binance: Binance-Peg Tokens

    # Create loan
    sfrxeth.approve(controller, 1000 * 10**18, sender=admin)
    controller.create_loan(1000 * 10**18, 400_000 * 10**18, 20, sender=admin)

    # Add liquidity
    stablecoin.approve(pools['USDC'], 100_000 * 10 ** 18, sender=admin)
    Contract(rtokens["USDC"]).approve(pools['USDC'], 100_000 * 10 ** 6, sender=admin)
    pools["USDC"].add_liquidity([100_000 * 10 ** 6, 100_000 * 10 ** 18], 200_000 * 10 ** 18, sender=admin)

    stablecoin.approve(pools['USDT'], 100_000 * 10 ** 18, sender=admin)
    Contract(rtokens["USDT"]).approve(pools['USDT'], 100_000 * 10 ** 6, sender=admin)
    pools["USDT"].add_liquidity([100_000 * 10 ** 6, 100_000 * 10 ** 18], 200_000 * 10 ** 18, sender=admin)

    stablecoin.approve(pools['USDP'], 100_000 * 10 ** 18, sender=admin)
    Contract(rtokens["USDP"]).approve(pools['USDP'], 100_000 * 10 ** 18, sender=admin)
    pools["USDP"].add_liquidity([100_000 * 10 ** 18, 100_000 * 10 ** 18], 200_000 * 10 ** 18, sender=admin)

    stablecoin.approve(pools['TUSD'], 100_000 * 10 ** 18, sender=admin)
    Contract(rtokens["TUSD"]).approve(pools['TUSD'], 100_000 * 10 ** 18, sender=admin)
    pools["TUSD"].add_liquidity([100_000 * 10 ** 18, 100_000 * 10 ** 18], 200_000 * 10 ** 18, sender=admin)

    # --- USER CREATES LOAN ---

    user = accounts.test_accounts[0]
    sfrxeth.transfer(user, 10 * 10 ** 18, sender="0x88441cCd7c41d4d6f4Edf7811C758065555226fA")
    sfrxeth.approve(controller, 10 * 10 ** 18, sender=user)
    controller.create_loan(10 * 10 ** 18, 16_300 * 10 ** 18, 20, sender=user)  # Close to max borrowable

    print('\n========================')
    print("===== LIQUIDATION  =====")
    print('========================\n')

    liquidator = accounts.test_accounts[1]
    sfrxeth.transfer(liquidator, 10 * 10 ** 18, sender="0x88441cCd7c41d4d6f4Edf7811C758065555226fA")
    liquidator_contract = account.deploy(project.SoftLiquidatorFork, amm, ROUTER, stablecoin, collateral, FRXETH)
    sfrxeth.approve(liquidator_contract, 2 ** 256 - 1, sender=liquidator)

    user_x_down_initial = amm.get_x_down(user)
    tranche = 10 ** 18  # sfrxETH
    sfrxeth.approve(liquidator_contract, 2 ** 256 - 1, sender=liquidator)

    router = Contract(ROUTER)
    liquidation_router_params = get_router_params(stablecoin.address, pools)["liquidation"]

    liquidation_profit_collateral_calc = 0
    liquidation_profit_stablecoin_calc = 0
    while True:
        price = price_oracle.price()

        while True:
            output, crv_usd, crv_usd_done = liquidator_contract.calc_output(
                tranche,
                True,
                liquidation_router_params['usdt']['route'],
                liquidation_router_params['usdt']['swap_params'],
                liquidation_router_params['usdt']['factory_swap_addresses'],
            )
            profit_collateral = output - tranche
            print("\n----------------------\n")
            print(f"Price: {price / 10 ** 18}")
            print(f"Profit collateral: {profit_collateral / 10 ** 18} sfrxETH")

            min_crv_usd = int(crv_usd_done * 0.998)
            min_output = int(output * 0.998)
            if 0 < crv_usd_done < crv_usd:
                frxeth_tranche = liquidator_contract.convert_to_assets(output)
                _expected_crv_usd = router.get_exchange_multiple_amount(
                    liquidation_router_params['usdt']['route'],
                    liquidation_router_params['usdt']['swap_params'],
                    frxeth_tranche,
                    liquidation_router_params['usdt']['factory_swap_addresses'],
                )
                _min_crv_usd = int(_expected_crv_usd * 0.998)
                if _min_crv_usd > crv_usd_done:
                    tranche = output
                    min_crv_usd = _min_crv_usd

                    profit_stablecoin = _expected_crv_usd - crv_usd_done
                    liquidation_profit_stablecoin_calc += profit_stablecoin
                    print(f"Profit stablecoin: {profit_stablecoin / 10 ** 18} crvUSD")
                else:
                    break
            elif profit_collateral < 10**17:
                break

            print(f"Tranche: {tranche / 10 ** 18} sfrxETH")
            liquidation_profit_collateral_calc += max(profit_collateral, 0)
            _balance = sfrxeth.balanceOf(liquidator)
            liquidator_contract.exchange(
                tranche,
                min_crv_usd,
                min_output,
                True,
                liquidation_router_params['usdt']['route'],
                liquidation_router_params['usdt']['swap_params'],
                liquidation_router_params['usdt']['factory_swap_addresses'],
                sender=liquidator,
                gas_limit=12_000_000,
            )
            print("Real collateral profit:", (sfrxeth.balanceOf(liquidator) - _balance) / 10**18)

        if controller.user_state(user)[0] == 0:
            break

        price_oracle.set_price(price * 98 // 100, sender=admin)
        chain.pending_timestamp += 5*60  # 5 minutes
        project.provider.mine()
        sleep(2)

    user_state_after_liquidation = controller.user_state(user)
    liquidation_profit_collateral = (sfrxeth.balanceOf(liquidator) - 10 * 10 ** 18)
    liquidation_profit_stablecoin = stablecoin.balanceOf(liquidator)

    print('\n========================')
    print("==== DE-LIQUIDATION ====")
    print('========================\n')

    tranche = 10**18  # sfrxETH
    deliquidation_profit_collateral_calc = 0
    deliquidation_router_params = get_router_params(stablecoin.address, pools)["deliquidation"]
    while True:
        price = price_oracle.price()

        while True:
            if controller.user_state(user)[1] == 0:
                break

            output, crv_usd, collateral_done = liquidator_contract.calc_output(
                tranche,
                False,
                deliquidation_router_params['usdt']['route'],
                deliquidation_router_params['usdt']['swap_params'],
                deliquidation_router_params['usdt']['factory_swap_addresses'],
            )
            profit_collateral = output - collateral_done
            print("\n----------------------\n")
            print(f"Price: {price / 10 ** 18}")
            print(f"Profit collateral: {profit_collateral / 10 ** 18} sfrxETH")
            print(f"Tranche: {tranche / 10 ** 18} sfrxETH")

            if profit_collateral < 10**17:
                break

            deliquidation_profit_collateral_calc += max(profit_collateral, 0)
            min_crv_usd = int(crv_usd * 0.998)
            min_output = int(output * 0.998)
            _balance = sfrxeth.balanceOf(liquidator)
            liquidator_contract.exchange(
                tranche,
                min_crv_usd,
                min_output,
                False,
                deliquidation_router_params['usdt']['route'],
                deliquidation_router_params['usdt']['swap_params'],
                deliquidation_router_params['usdt']['factory_swap_addresses'],
                sender=liquidator,
                gas_limit=12_000_000,
            )
            print("Real collateral profit:", (sfrxeth.balanceOf(liquidator) - _balance) / 10**18)

        if controller.user_state(user)[1] == 0:
            break

        price_oracle.set_price(price * 102 // 100, sender=admin)
        chain.pending_timestamp += 5 * 60  # 5 minutes
        project.provider.mine()
        sleep(2)

    user_state_after_deliquidation = controller.user_state(user)
    deliquidation_profit_collateral = (
                sfrxeth.balanceOf(liquidator) - liquidation_profit_collateral - 10 * 10 ** 18)
    deliquidation_profit_stablecoin = stablecoin.balanceOf(liquidator) - liquidation_profit_stablecoin

    print('\n========================')
    print('======== START =========')
    print('========================\n')
    print('User collateral:                       10 sfrxETH')
    print('User stablecoin equivalent (x_down):  ', user_x_down_initial / 10 ** 18, 'crvUSD')

    print('\n========================')
    print("===== LIQUIDATION  =====")
    print('========================\n')
    print('User collateral:                      ', user_state_after_liquidation[0] / 10 ** 18, 'sfrxETH')
    print('User stablecoin:                      ', user_state_after_liquidation[1] / 10 ** 18, 'crvUSD')
    print('Expected liquidator profit:           ',
          liquidation_profit_collateral_calc / 10 ** 18, "sfrxETH,",
          liquidation_profit_stablecoin_calc / 10 ** 18, 'crvUSD')
    print('Liquidator profit:                    ',
          liquidation_profit_collateral / 10 ** 18, 'sfrxETH,',
          liquidation_profit_stablecoin / 10 ** 18, 'crvUSD')

    print('\n========================')
    print("==== DE-LIQUIDATION ====")
    print('========================\n')
    print('User collateral:                      ', user_state_after_deliquidation[0] / 10 ** 18, 'sfrxETH')
    print('User stablecoin:                      ', user_state_after_deliquidation[1] / 10 ** 18, 'crvUSD')
    print('Expected de-liquidator profit:        ',
          deliquidation_profit_collateral_calc / 10 ** 18, "sfrxETH,",
          0.0, 'crvUSD')
    print('De-liquidator profit:                 ',
          deliquidation_profit_collateral / 10 ** 18, 'sfrxETH,',
          deliquidation_profit_stablecoin / 10 ** 18, 'crvUSD')

    import IPython
    IPython.embed()
