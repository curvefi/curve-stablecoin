from ape import project, accounts, Contract, networks
from ape.cli import NetworkBoundCommand, network_option
from ape.logging import logger
# account_option could be used when in prod?
import click

from dotenv import load_dotenv
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ADDRESS_PROVIDER = "0x0000000022D53366457F9d5E68Ec105046FC4383"
METAREGISTRY = "0xF98B45FA17DE75FB1aD0e7aFD971b0ca00e379fC"
BASE_POOL_REGISTRY = "0xDE3eAD9B2145bBA2EB74007e58ED07308716B725"
STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID = 8
USDP = "0x8E870D67F660D95d5be530380D0eC0bd388289E1"

# set before executing
STABLESWAP_FACTORY = ""
STABLECOIN = ""


def _get_deployment_kw(network):
    
    kw = {}

    if not 'ethereum:' in network:
        return

    is_sim = "ethereum:mainnet-fork" in network
    
    if not is_sim:
        
        account = accounts.load('babe')
        max_base_fee = networks.active_provider.base_fee * 2
        kw = {
            'max_fee': max_base_fee,
            'max_priority_fee': min(int(0.5e9), max_base_fee)
        }
        account.set_autosign(True)

    else:
        
        account = accounts["0xbabe61887f1de2713c6f97e567623453d3C79f67"]        
    
    return account, kw


@click.group()
def cli():
    """
    Script for production deployment of crvUSD
    """
    
    
@cli.command(cls=NetworkBoundCommand)
@network_option()
def clean(network):
    
    account, kw = _get_deployment_kw(network=network)
    
    address_provider = Contract(ADDRESS_PROVIDER)
    address_provider_admin = Contract(address_provider.admin())
    
    with accounts.use_sender(account) as account:
        
        # unset addresses:
        for registry_id in [9, 10]:  # we want to remove 9 and 10. 8 is still reserved.
            
            if address_provider.get_address(registry_id) == ZERO_ADDRESS:
                continue
            
            address_provider_admin.execute(
                address_provider,
                address_provider.unset_address.encode_input(
                    registry_id,
                    **kw
                ),
            )
        
            # sanity check:
            assert address_provider.get_address(registry_id) == ZERO_ADDRESS
            logger.info(f"Cleaned AddressProvider Registry ID: {registry_id}")


@cli.command(cls=NetworkBoundCommand)
@network_option()
def setup(network):
    
    account, kw = _get_deployment_kw(network=network)
    
    if not STABLESWAP_FACTORY or STABLECOIN:
        logger.error("Addresses for stableswap factory and stablecoin not set.")
        raise
    
    # ----------------- write to the chain -----------------
    
    with accounts.use_sender(account) as account:
        
        # -------------------- ADDRESSPROVIDER INTEGRATION -------------------------
        
        address_provider = Contract(ADDRESS_PROVIDER)
        address_provider_admin = Contract(address_provider.admin())
        
        occupied_slot = address_provider.get_address(STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID)
        if occupied_slot == ZERO_ADDRESS:
            # we should not be in this branch, since slot is already registered for factory
            logger.error("Empty slot for crvusd plain pools factory")
        
        logger.info(f"Registry at AddressProvider Registry ID: {STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID}: {occupied_slot}")
        logger.info("Updating to new registry ...")

        # update existing address provider id with new stableswap factory:
        address_provider_admin.execute(
            address_provider,
            address_provider.set_address.encode_input(
                STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID,
                STABLESWAP_FACTORY,
                **kw
            ),
        )
        assert address_provider.get_address(STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID) == STABLESWAP_FACTORY
        logger.info(f"Updated AddressProvider Registry ID: {STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID} with {STABLESWAP_FACTORY}")
        
        # -------------------- METAREGISTRY INTEGRATION -------------------------
        
        # deploy factory handler:
        logger.info("Deploying new factory handler for stableswap factory ...")
        factory_handler = account.deploy(project.StableswapFactoryHandler, STABLESWAP_FACTORY, BASE_POOL_REGISTRY)
        
        # integrate into metaregistry:
        metaregistry = Contract("0xF98B45FA17DE75FB1aD0e7aFD971b0ca00e379fC")
        previous_factory_handler = metaregistry.find_pool_for_coins(STABLECOIN, USDP, 0)
        factory_handler_integrated = previous_factory_handler != ZERO_ADDRESS
        
        if not factory_handler_integrated:
            
            logger.info("First integration ... adding factory handler to the metaregistry")
        
            # first integration into metaregistry:
            address_provider_admin.execute(
                metaregistry.address,
                metaregistry.add_registry_handler.encode_input(factory_handler),
            )
            
        else:  # redeployment, which means update handler index in metaregistry.
            
            logger.info("Redeployment ... updating factory handler to the metaregistry")
            
            # get index of previous factory handler first:
            for idx in range(1000):
                if metaregistry.get_registry(idx) == previous_factory_handler:
                    break
            
            # update that idx with newly deployed factory handler:
            address_provider_admin.execute(
                metaregistry.address,
                metaregistry.update_registry_handler.encode_input(
                    idx, factory_handler.address
                )
            )
            
            assert metaregistry.get_registry(idx) == factory_handler.address

        # sanity check:
        factory = Contract(STABLESWAP_FACTORY)
        pool_addr = factory.find_pool_for_coins(STABLECOIN, USDP, 0)
        assert metaregistry.find_pool_for_coins(STABLECOIN, USDP, 0) == pool_addr
