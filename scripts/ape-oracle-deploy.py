# This script simply tests the deployment process

from ape import project, accounts, networks
from ape.cli import NetworkBoundCommand, network_option
# account_option could be used when in prod?
import click

from dotenv import load_dotenv
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


TRICRYPTO = "0xD51a44d3FaE010294C616388b506AcdA1bfAAE46"
FRXETH_POOL = "0xa1f8a6807c402e4a15ef4eba36528a3fed24e577"
CHAINLINK_ETH = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
SFRXETH = "0xac3E018457B222d93114458476f3E3416Abbe38F"


@click.group()
def cli():
    """
    Script for testing the deployment process in ape
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
        account.deploy(
                project.CryptoWithStablePriceAndChainlinkFrxeth,
                TRICRYPTO,  # Tricrypto
                1,  # price index with ETH
                "0x6F333fD5642eBc96040dF684489Db550e788E9Ed",  # old USDT pool
                FRXETH_POOL,  # staked swap (frxeth/eth)
                "0x832f436Ad2813c76AAe756703CAcB5c1028d11Da",  # Agg
                CHAINLINK_ETH,  # ETH/USD Chainlink aggregator
                SFRXETH,  # sFrxETH
                600,
                1,  # 1% bound
                **kw)
