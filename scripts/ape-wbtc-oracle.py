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

PEG_KEEPERS = ['0xaA346781dDD7009caa644A4980f044C50cD2ae22', '0xE7cd2b4EB1d98CD6a4A48B6071D46401Ac7DC5C8', '0x6B765d07cf966c745B340AdCa67749fE75B5c345', '0x1ef89Ed0eDd93D1EC09E4c07373f69C49f4dcCae']
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

TRICRYPTO = ["0x7F86Bf177Dd4F3494b841a37e810A34dD56c829B", "0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4"]  # USDC, USDT
CRVUSD_POOLS = ["0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E", "0x390f3595bca2df7d23783dfd126427cceb997bf4"]  # USDC, USDT
FACTORY = "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"
CHAINLINK_BTC = "0xf4030086522a5beea4988f8ca5b36dbc97bee88c"
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
    account = accounts.load('babe')
    account.set_autosign(True)

    max_fee = networks.active_provider.base_fee * 2
    max_priority_fee = int(0.5e9)
    kw = {'max_fee': max_fee, 'max_priority_fee': max_priority_fee}

    with accounts.use_sender(account):
        oracle = account.deploy(
                project.CryptoWithStablePriceWstethN,
                TRICRYPTO,
                [0, 0],  # price index with WBTC
                CRVUSD_POOLS,  # CRVUSD stableswaps
                AGG,
                FACTORY,
                CHAINLINK_BTC,
                BOUND_SIZE,
                **kw)

        oracle.price_w(**kw)

    print('========================')
    print('Price Oracle:      ', oracle.address)
