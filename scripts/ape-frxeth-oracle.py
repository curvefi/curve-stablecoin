# Deployed at:
# https://etherscan.io/address/0x28d7880B5b67fB4a0B1c6Ed6c33c33f365113C29

from ape import project, accounts, networks
from ape.cli import NetworkBoundCommand, network_option

# account_option could be used when in prod?
import click

from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


STABLECOIN = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"

TRICRYPTO = [
    "0x7F86Bf177Dd4F3494b841a37e810A34dD56c829B",
    "0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4",
]  # USDC, USDT
CRVUSD_POOLS = [
    "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E",
    "0x390f3595bca2df7d23783dfd126427cceb997bf4",
]  # USDC, USDT
FRXETH_POOL = "0x9c3b46c0ceb5b9e304fcd6d88fc50f7dd24b31bc"
SFRXETH = "0xac3E018457B222d93114458476f3E3416Abbe38F"
FACTORY = "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"
CHAINLINK_ETH = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
AGG = "0x18672b1b0c623a30089A280Ed9256379fb0E4E62"
# MONETARY_POLICY = "0xb8687d7dc9d8fa32fabde63E19b2dBC9bB8B2138"
BOUND_SIZE = int(0.015 * 1e18)


@click.group()
def cli():
    """
    Script for deploying sfrxETH oracle
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
            project.CryptoWithStablePriceFrxethN,
            TRICRYPTO,
            [1, 1],  # price index with ETH
            CRVUSD_POOLS,  # CRVUSD stableswaps
            FRXETH_POOL,  # staked swap (frxeth/weth)
            AGG,
            FACTORY,
            SFRXETH,
            CHAINLINK_ETH,
            BOUND_SIZE,
            **kw,
        )

        oracle.price_w(**kw)

    print("========================")
    print("Price Oracle:      ", oracle.address)
