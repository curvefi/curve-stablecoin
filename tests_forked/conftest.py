from pathlib import Path

import pytest
from ape import accounts, Contract
from dotenv import load_dotenv
from .utils import deploy_test_blueprint, mint_tokens_for_testing

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


def pytest_configure():
    pytest.SHORT_NAME = "crvUSD"
    pytest.FULL_NAME = "Curve.Fi USD Stablecoin"
    pytest.rtokens = {
        "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "USDP": "0x8E870D67F660D95d5be530380D0eC0bd388289E1",
        "TUSD": "0x0000000000085d4780B73119b644AE5ecd22b376",
    }
    pytest.ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
    pytest.POOL_NAME = "crvUSD/{name}"
    pytest.POOL_SYMBOL = "crvUSD{name}"
    pytest.STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID = 8  # reserve slot for crvusd plain pools factory

    pytest.stable_A = 500  # initially, can go higher later
    pytest.stable_fee = 1000000  # 0.01%
    pytest.stable_asset_type = 0
    pytest.stable_ma_exp_time = 866  # 10 min / ln(2)

    pytest.OWNERSHIP_ADMIN = "0x40907540d8a6C65c637785e8f8B742ae6b0b9968"
    pytest.TRICRYPTO = "0xD51a44d3FaE010294C616388b506AcdA1bfAAE46"

    pytest.initial_pool_coin_balance = 500_000  # of both coins
    pytest.initial_eth_balance = 1000  # both eth and weth
    
    # registry integration:
    pytest.base_pool_registry = "0xDE3eAD9B2145bBA2EB74007e58ED07308716B725"
    pytest.metaregistry = "0xF98B45FA17DE75FB1aD0e7aFD971b0ca00e379fC"
    pytest.address_provider = "0x0000000022D53366457F9d5E68Ec105046FC4383"
    pytest.registry_name = "crvUSD plain pools"
    pytest.new_id_created = False
    pytest.max_id_before = 0
    pytest.handler_index = None
    
    # record stablecoin address:
    pytest.stablecoin = pytest.ZERO_ADDRESS


"""
We use autouse=True to automatically deploy all during all tests
"""


@pytest.fixture(scope="module", autouse=True)
def forked_admin(accounts):
    return accounts[0]


@pytest.fixture(scope="module", autouse=True)
def forked_fee_receiver(accounts):
    return accounts[1]


@pytest.fixture(scope="module", autouse=True)
def weth():
    return Contract("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")


@pytest.fixture(scope="module", autouse=True)
def forked_user(project, accounts, weth):
    acc = accounts[2]
    mint_tokens_for_testing(project, acc, pytest.initial_pool_coin_balance, pytest.initial_eth_balance)
    return acc


@pytest.fixture(scope="module", autouse=True)
def stablecoin(project, forked_admin):
    _stablecoin = forked_admin.deploy(project.Stablecoin, pytest.FULL_NAME, pytest.SHORT_NAME)
    pytest.stablecoin = _stablecoin.address
    return _stablecoin


@pytest.fixture(scope="module", autouse=True)
def controller_impl(project, forked_admin):
    return deploy_test_blueprint(project, project.Controller, forked_admin)


@pytest.fixture(scope="module", autouse=True)
def amm_impl(project, forked_admin):
    return deploy_test_blueprint(project, project.AMM, forked_admin)


@pytest.fixture(scope="module")
def controller_factory(
    project,
    forked_admin,
    stablecoin,
    weth,
    forked_fee_receiver,
    controller_impl,
    amm_impl,
):
    factory = forked_admin.deploy(
        project.ControllerFactory,
        stablecoin.address,
        forked_admin,
        forked_fee_receiver,
        weth.address,
    )
    factory.set_implementations(controller_impl, amm_impl, sender=forked_admin)
    stablecoin.set_minter(factory.address, sender=forked_admin)
    return factory


@pytest.fixture(scope="module", autouse=True)
def stableswap_factory(project, forked_admin, forked_fee_receiver, stablecoin):
    swap_factory = forked_admin.deploy(project.StableswapFactory, forked_fee_receiver)
    swap_factory.add_token_to_whitelist(stablecoin, True, sender=forked_admin)
    return swap_factory


@pytest.fixture(scope="module", autouse=True)
def owner_proxy(project, forked_admin, stableswap_factory):
    # Ownership admin is account temporarily, will need to become OWNERSHIP_ADMIN
    owner_proxy = forked_admin.deploy(
        project.OwnerProxy,
        forked_admin,
        forked_admin,
        forked_admin,
        stableswap_factory,
        pytest.ZERO_ADDRESS,
    )

    with accounts.use_sender(forked_admin):
        stableswap_factory.commit_transfer_ownership(owner_proxy)
        owner_proxy.accept_transfer_ownership(stableswap_factory)
    return owner_proxy


@pytest.fixture(scope="module", autouse=True)
def stableswap_impl(project, forked_admin, stableswap_factory, owner_proxy):
    # Set implementations
    stableswap_impl = forked_admin.deploy(project.Stableswap)

    with accounts.use_sender(forked_admin):
        owner_proxy.set_plain_implementations(
            stableswap_factory, 2, [stableswap_impl.address] + [pytest.ZERO_ADDRESS] * 9
        )
        gauge_impl = Contract("0x5aE854b098727a9f1603A1E21c50D52DC834D846")
        owner_proxy.set_gauge_implementation(stableswap_factory, gauge_impl)
    return stableswap_impl


@pytest.fixture(scope="module", autouse=True)
def address_provider(stableswap_factory):
    
    address_provider = Contract("0x0000000022D53366457F9d5E68Ec105046FC4383")
    
    # Put factory in address provider / registry
    with accounts.use_sender("0x7EeAC6CDdbd1D0B8aF061742D41877D7F707289a"):
        address_provider_admin = Contract(address_provider.admin())
        pytest.max_id_before = address_provider.max_id()
        
        if address_provider.get_address(pytest.STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID) == pytest.ZERO_ADDRESS:
            
            # this branch should not never be executed since the registry slot exists.
            # we test this later.
            address_provider_admin.execute(
                address_provider,
                address_provider.add_new_id.encode_input(stableswap_factory, pytest.registry_name),
            )
            pytest.new_id_created = True
        
        else:
            
            address_provider_admin.execute(
                address_provider,
                address_provider.set_address.encode_input(
                    pytest.STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID,
                    stableswap_factory
                ),
            )    
        
    return address_provider


@pytest.fixture(scope="module", autouse=True)
def rtokens_pools(project, forked_admin, owner_proxy, stablecoin, stableswap_impl, stableswap_factory):
    pools = {}

    # Deploy pools
    for name, rtoken in pytest.rtokens.items():
        tx = owner_proxy.deploy_plain_pool(
            pytest.POOL_NAME.format(name=name),
            pytest.POOL_SYMBOL.format(name=name),
            [rtoken, stablecoin.address, pytest.ZERO_ADDRESS, pytest.ZERO_ADDRESS],
            pytest.stable_A,
            pytest.stable_fee,
            pytest.stable_asset_type,
            0,  # implentation_idx
            pytest.stable_ma_exp_time,
            sender=forked_admin,
        )
        # This is a workaround: instead of getting return_value we parse events to get the pool address
        # This is because reading return_value in ape is broken
        pool = project.Stableswap.at(tx.events.filter(stableswap_factory.PlainPoolDeployed)[0].pool)
        pools[name] = pool
    return pools


@pytest.fixture(scope="module", autouse=True)
def factory_handler(project, stableswap_factory, forked_admin):
    return project.StableswapFactoryHandler.deploy(
        stableswap_factory.address, pytest.base_pool_registry, sender=forked_admin
    )


@pytest.fixture(scope="module", autouse=True)
def metaregistry(address_provider, rtokens_pools, factory_handler):
    
    address_provider_admin = Contract(address_provider.admin())
    _metaregistry = Contract(pytest.metaregistry)
    
    previous_factory_handler = _metaregistry.find_pool_for_coins(
        pytest.stablecoin, pytest.rtokens["USDP"], 0
    )
    factory_handler_integrated = previous_factory_handler != pytest.ZERO_ADDRESS
    
    with accounts.use_sender("0x7EeAC6CDdbd1D0B8aF061742D41877D7F707289a"):
        
        if not factory_handler_integrated:
        
            # first integration into metaregistry:
            address_provider_admin.execute(
                _metaregistry.address,
                _metaregistry.add_registry_handler.encode_input(factory_handler),
            )
            
        else:  # redeployment, which means update handler index in metaregistry.
            
            # get index of previous factory handler first:
            for idx in range(1000):
                if metaregistry.get_registry(idx) == previous_factory_handler:
                    break
            
            # update that idx with newly deployed factory handler:
            address_provider_admin.execute(
                _metaregistry.address,
                _metaregistry.update_registry_handler.encode_input(
                    idx, factory_handler.address
                )
            )
            
            assert metaregistry.get_registry(idx) == factory_handler.address
            
    return _metaregistry


@pytest.fixture(scope="module", autouse=True)
def agg_stable_price(project, forked_admin, stablecoin, rtokens_pools):
    agg = forked_admin.deploy(project.AggregateStablePrice, stablecoin, 10**15, forked_admin)
    for pool in rtokens_pools.values():
        agg.add_price_pair(pool, sender=forked_admin)
    agg.set_admin(pytest.OWNERSHIP_ADMIN, sender=forked_admin)  # Alternatively, we can make it ZERO_ADDRESS

    return agg


@pytest.fixture(scope="module", autouse=True)
def peg_keepers(project, forked_admin, forked_fee_receiver, rtokens_pools, controller_factory, agg_stable_price):
    peg_keepers = []
    for pool in rtokens_pools.values():
        peg_keeper = forked_admin.deploy(
            project.PegKeeper,
            pool,
            1,
            forked_fee_receiver,
            2 * 10**4,
            controller_factory,
            agg_stable_price,
            forked_admin.address,
        )
        peg_keepers.append(peg_keeper)

    return peg_keepers


@pytest.fixture(scope="module", autouse=True)
def policy(project, forked_admin, peg_keepers, controller_factory, agg_stable_price):
    return forked_admin.deploy(
        project.AggMonetaryPolicy,
        forked_admin,
        agg_stable_price,
        controller_factory,
        peg_keepers + [pytest.ZERO_ADDRESS],
        627954226,  # rate = 2%
        2 * 10**16,  # sigma
        5 * 10**16,
    )  # Target debt fraction


@pytest.fixture(scope="module", autouse=True)
def price_oracle(project, forked_admin, rtokens_pools, agg_stable_price):
    return forked_admin.deploy(
        project.CryptoWithStablePrice,
        pytest.TRICRYPTO,
        1,  # price index with ETH
        rtokens_pools["USDT"],
        agg_stable_price,
        600,
    )


@pytest.fixture(scope="module")
def chainlink_aggregator():
    return Contract("0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419")


@pytest.fixture(scope="module", autouse=True)
def price_oracle_with_chainlink(project, forked_admin, rtokens_pools, agg_stable_price, chainlink_aggregator):
    return forked_admin.deploy(
        project.CryptoWithStablePriceAndChainlink,
        pytest.TRICRYPTO,
        1,  # price index with ETH
        rtokens_pools["USDT"],
        agg_stable_price,
        chainlink_aggregator.address,
        600,
        1
    )
