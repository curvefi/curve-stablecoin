# This script simply tests the deployment process

from ape import project, accounts, networks
from ape.cli import NetworkBoundCommand, network_option
# account_option could be used when in prod?
import click

from dotenv import load_dotenv
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


ADMIN = "0x40907540d8a6C65c637785e8f8B742ae6b0b9968"  # Ownership admin
PRICE_ORACLE = "0xe5Afcf332a5457E8FafCD668BcE3dF953762Dfe7"  # Agg
CONTROLLER_FACTORY = "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"
PEG_KEEPERS = [
        '0xaA346781dDD7009caa644A4980f044C50cD2ae22',
        '0xE7cd2b4EB1d98CD6a4A48B6071D46401Ac7DC5C8',
        '0x6B765d07cf966c745B340AdCa67749fE75B5c345',
        '0x1ef89Ed0eDd93D1EC09E4c07373f69C49f4dcCae',
        '0x0000000000000000000000000000000000000000']
RATE = int((1.1**(1 / (365 * 86400)) - 1) * 1e18)  # 10% if PegKeepers are empty, 4% when at target fraction
SIGMA = 2 * 10**16  # 2% when at target debt fraction
DEBT_FRACTION = 10 * 10**16  # 10%


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
        mpolicy = account.deploy(
                project.AggMonetaryPolicy2,
                ADMIN,
                PRICE_ORACLE,
                CONTROLLER_FACTORY,
                PEG_KEEPERS,
                RATE,
                SIGMA,
                DEBT_FRACTION,
                **kw)
        print(mpolicy.rate('0x8472A9A7632b173c8Cf3a86D3afec50c35548e76'))
