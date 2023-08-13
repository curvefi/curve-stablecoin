from ape import project, accounts, networks
from ape.cli import NetworkBoundCommand, network_option
import click

# Deployed at:
# https://etherscan.io/address/0xbef434e2acf0fbad1f0579d2376fed0d1cfc4217#code

from dotenv import load_dotenv
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


STABLECOIN = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"

TRICRYPTO = "0x2889302a794da87fbf1d6db415c1492194663d13"
FACTORY = "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"
CHAINLINK_BTC = "0xf4030086522a5beea4988f8ca5b36dbc97bee88c"
BOUND_SIZE = int(0.015 * 1e18)

AGG = "0x18672b1b0c623a30089A280Ed9256379fb0E4E62"


@click.group()
def cli():
    """
    Script for deploying TBTC oracle
    """


@cli.command(
    cls=NetworkBoundCommand,
)
@network_option()
def deploy(network):
    account = accounts.load('babe')
    account.set_autosign(True)

    max_fee = networks.active_provider.base_fee * 2
    max_priority_fee = int(0.5e9)
    kw = {'max_fee': max_fee, 'max_priority_fee': max_priority_fee}

    with accounts.use_sender(account):
        oracle = account.deploy(
                project.CryptoWithStablePriceTBTC,
                TRICRYPTO,
                0,  # price index with TBTC
                AGG,
                FACTORY,
                CHAINLINK_BTC,
                BOUND_SIZE,
                **kw)

        oracle.price_w(**kw)

    print('========================')
    print('Price Oracle:      ', oracle.address)
    print('Price:             ', oracle.price() / 1e18)
