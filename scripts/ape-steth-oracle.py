from ape import project, accounts, networks
from ape.cli import NetworkBoundCommand, network_option

# account_option could be used when in prod?
import click

from dotenv import load_dotenv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(Path(BASE_DIR, ".env"))


STABLECOIN = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"
AGG_SIGMA = 10**15
ALL_CRVUSD_POOLS = [
    "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E",
    "0x390f3595bCa2Df7d23783dFd126427CCeb997BF4",
    "0xCa978A0528116DDA3cbA9ACD3e68bc6191CA53D0",
    "0x34D655069F4cAc1547E4C8cA284FfFF5ad4A8db0",
]
OWNERSHIP_ADMIN = "0x40907540d8a6C65c637785e8f8B742ae6b0b9968"

PEG_KEEPERS = [
    "0xaA346781dDD7009caa644A4980f044C50cD2ae22",
    "0xE7cd2b4EB1d98CD6a4A48B6071D46401Ac7DC5C8",
    "0x6B765d07cf966c745B340AdCa67749fE75B5c345",
    "0x1ef89Ed0eDd93D1EC09E4c07373f69C49f4dcCae",
]
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

policy_rate = int(
    (1.09 ** (1 / (365 * 86400)) - 1) * 1e18
)  # 9% if PegKeepers are empty, 3.6% when at target fraction
policy_sigma = 2 * 10**16  # 2% when at target debt fraction
policy_debt_fraction = 10 * 10**16  # 10%

TRICRYPTO = [
    "0x7F86Bf177Dd4F3494b841a37e810A34dD56c829B",
    "0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4",
]  # USDC, USDT
CRVUSD_POOLS = [
    "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E",
    "0x390f3595bca2df7d23783dfd126427cceb997bf4",
]  # USDC, USDT
STETH_POOL = "0x21e27a5e5513d6e65c4f830167390997aa84843a"
WSTETH = "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0"
FACTORY = "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"
CHAINLINK_ETH = "0x5f4eC3Df9cbd43714FE2740f5E3616155c5b8419"
CHAINLINK_STETH = "0x86392dC19c0b719886221c78AB11eb8Cf5c52812"
BOUND_SIZE = int(0.015 * 1e18)


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
        agg = account.deploy(
            project.AggregateStablePrice2, STABLECOIN, AGG_SIGMA, account, **kw
        )
        for pool in ALL_CRVUSD_POOLS:
            agg.add_price_pair(pool, **kw)
        agg.set_admin(OWNERSHIP_ADMIN, **kw)

        policy = account.deploy(
            project.AggMonetaryPolicy2,
            OWNERSHIP_ADMIN,
            agg,
            FACTORY,
            PEG_KEEPERS + [ZERO_ADDRESS],
            policy_rate,
            policy_sigma,
            policy_debt_fraction,
            **kw,
        )

        oracle = account.deploy(
            project.CryptoWithStablePriceWstethN,
            TRICRYPTO,
            [1, 1],  # price index with ETH
            CRVUSD_POOLS,  # CRVUSD stableswaps
            STETH_POOL,  # staked swap (steth/eth)
            agg,
            FACTORY,
            WSTETH,
            CHAINLINK_ETH,
            CHAINLINK_STETH,
            BOUND_SIZE,
            **kw,
        )

        agg.price_w(**kw)
        oracle.price_w(**kw)
        policy.rate_write("0x8472A9A7632b173c8Cf3a86D3afec50c35548e76", **kw)

    print("========================")
    print("Price Aggregator:  ", agg.address)
    print("Aggregator price:  ", agg.price() / 1e18)
    print("Monetary policy:   ", policy.address)
    print(
        "Sample rate:       ", policy.rate("0x8472A9A7632b173c8Cf3a86D3afec50c35548e76")
    )
    print("Price Oracle:      ", oracle.address)
