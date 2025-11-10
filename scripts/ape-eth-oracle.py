from ape import project, accounts, networks
from ape.cli import NetworkBoundCommand, network_option

# account_option could be used when in prod?
import click

from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


STABLECOIN = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"
OWNERSHIP_ADMIN = "0x40907540d8a6C65c637785e8f8B742ae6b0b9968"

TRICRYPTO = [
    "0x7F86Bf177Dd4F3494b841a37e810A34dD56c829B",
    "0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4",
]  # USDC, USDT
CRVUSD_POOLS = [
    "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E",
    "0x390f3595bca2df7d23783dfd126427cceb997bf4",
]  # USDC, USDT
FACTORY = "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"
CHAINLINK_ETH = "0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419"
BOUND_SIZE = int(0.015 * 1e18)

AGG = "0x18672b1b0c623a30089A280Ed9256379fb0E4E62"


@click.group()
def cli():
    """
    Script for deploying wstETH oracle, new aggreagtor and a new monetary policy
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
        oracle = account.deploy(
            project.CryptoWithStablePriceETH,
            TRICRYPTO,
            [1, 1],  # price index with ETH
            CRVUSD_POOLS,  # CRVUSD stableswaps
            AGG,
            FACTORY,
            CHAINLINK_ETH,
            BOUND_SIZE,
            **kw,
        )

        oracle.price_w(**kw)

    print("========================")
    print("Price Oracle:      ", oracle.address)
    print("Price:             ", oracle.price() / 1e18)
