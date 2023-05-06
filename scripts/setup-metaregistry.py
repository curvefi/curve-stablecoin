from ape import project, accounts, Contract, networks
from ape.cli import NetworkBoundCommand, network_option
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
STABLESWAP_FACTORY = ""


@click.group()
def cli():
    """
    Script for production deployment of crvUSD
    """


@cli.command(cls=NetworkBoundCommand)
@network_option()
def deploy(network):
    
    kw = {}

    # Ethereum business only here:
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

    else:
        
        account = accounts["0xbabe61887f1de2713c6f97e567623453d3C79f67"]
    
    # set autosign so deployment is seamless:
    account.set_autosign(True)
    
    # ----------------- write to the chain -----------------
    
    with accounts.use_sender(account) as account:
        
        # Put factory in address provider / registry
        address_provider = Contract(ADDRESS_PROVIDER)
        address_provider_admin = Contract(address_provider.admin())
        
        if address_provider.get_address(STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID) == ZERO_ADDRESS:
            # we should not be in this branch, since slot is already registered for factory
            raise
            
        # update existing address provider id with new stableswap factory:
        assert STABLESWAP_FACTORY
        address_provider_admin.execute(
            address_provider,
            address_provider.set_address.encode_input(
                STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID,
                STABLESWAP_FACTORY,
                **kw
            ),
        )
        
        # deploy factory handler:
        factory_handler = project.StableswapFactoryHander.deploy(STABLESWAP_FACTORY, BASE_POOL_REGISTRY)
        
        # integrate into metaregistry:
