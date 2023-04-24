# This script simply tests the deployment process

from ape import project, accounts, networks
from ape.cli import NetworkBoundCommand, network_option
# account_option could be used when in prod?
import click

from dotenv import load_dotenv
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


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
    max_priority_fee = '0.5 gwei'

    with accounts.use_sender(account):
        account.deploy(project.DummyPriceOracle, account, 2000 * 10**18, max_fee=max_fee,
                       max_priority_fee=max_priority_fee)
