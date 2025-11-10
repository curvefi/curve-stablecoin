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
PRICE_ORACLE = "0x18672b1b0c623a30089A280Ed9256379fb0E4E62"  # Agg
CONTROLLER_FACTORY = "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"
PEG_KEEPERS = [
    "0xaA346781dDD7009caa644A4980f044C50cD2ae22",
    "0xE7cd2b4EB1d98CD6a4A48B6071D46401Ac7DC5C8",
    "0x6B765d07cf966c745B340AdCa67749fE75B5c345",
    "0x1ef89Ed0eDd93D1EC09E4c07373f69C49f4dcCae",
    "0x0000000000000000000000000000000000000000",
]
RATE = int(
    (1.06 ** (1 / (365 * 86400)) - 1) * 1e18
)  # 6% if PegKeepers are empty, 2.2% when at target fraction
SIGMA = 2 * 10**16  # 2% when at target debt fraction
DEBT_FRACTION = 10 * 10**16  # 10%

MARKETS = {
    "WBTC": "0x4e59541306910ad6dc1dac0ac9dfb29bd9f15c67",
    "ETH": "0xa920de414ea4ab66b97da1bfe9e6eca7d4219635",
}


@click.group()
def cli():
    """
    Deployer for monetary policy
    """


@cli.command(
    cls=NetworkBoundCommand,
)
@network_option()
def deploy(network):
    account = accounts.load("babe")
    account.set_autosign(True)

    max_fee = networks.active_provider.base_fee * 2
    max_priority_fee = int(0.5e9)
    kw = {"max_fee": max_fee, "max_priority_fee": max_priority_fee}

    with accounts.use_sender(account):
        for i, market in enumerate(MARKETS.keys()):
            mpolicy = account.deploy(
                project.AggMonetaryPolicy2,
                ADMIN,
                PRICE_ORACLE,
                CONTROLLER_FACTORY,
                PEG_KEEPERS,
                RATE,
                SIGMA,
                DEBT_FRACTION,
                **kw,
            )
            print("Market:", market)
            print("Policy:", mpolicy.address)
            print(
                "Rate:", (1 + mpolicy.rate(MARKETS[market]) / 1e18) ** (365 * 86400) - 1
            )
            print()
