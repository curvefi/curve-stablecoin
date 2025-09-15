#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from networks import ARBITRUM, ARBISCAN_API_KEY
from networks import NETWORK, ETHERSCAN_API_KEY


FACTORY = "0xcaEC110C784c9DF37240a8Ce096D352A75922DeA"
# STABLECOIN() in factory is crvUSD
WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
WBTC = "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f"
ARB = "0x912CE59144191C1204E64559FE8253a0e49E6548"

CHAIN_ID = 42161
GAUGE_FUNDER = "0x7a16fF8270133F063aAb6C9977183D9e72835428"


INDEXES = [0, 1, 5, 4]
MINMAX = {
    0: (0.01, 0.25),  # ETH, market at 9.5%
    1: (0.01, 0.25),  # WBTC, market at 8.2%
    5: (0.02, 0.30),  # ARB, market at 11%
    4: (0.05, 0.40),  # CRV
}


def account_load(fname):
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == "__main__":
    babe_raw = account_load("babe")

    if "--fork" in sys.argv[1:]:
        boa.env.fork(ARBITRUM)
        boa.env.eoa = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
    else:
        boa.set_network_env(ARBITRUM)
        boa.env.add_account(babe_raw)
        boa.env._fork_try_prefetch_state = False

    factory = boa.load_partial(
        "contracts/lending/deprecated/OneWayLendingFactoryL2.vy"
    ).at(FACTORY)
    gauge_factory = boa.from_etherscan(
        factory.gauge_factory(),
        name="GaugeFactory",
        uri="https://api.arbiscan.io/api",
        api_key=ARBISCAN_API_KEY,
    )

    gauges = {}
    salts = {}

    for ix in INDEXES:
        old_controller = boa.from_etherscan(
            factory.controllers(ix),
            name="Controller",
            uri="https://api.arbiscan.io/api",
            api_key=ARBISCAN_API_KEY,
        )
        old_amm = boa.from_etherscan(
            old_controller.amm(),
            name="AMM",
            uri="https://api.arbiscan.io/api",
            api_key=ARBISCAN_API_KEY,
        )
        name = factory.names(ix) + "2"
        vault = factory.create(
            old_controller.borrowed_token(),
            old_controller.collateral_token(),
            old_amm.A(),
            old_amm.fee(),
            old_controller.loan_discount(),
            old_controller.liquidation_discount(),
            old_amm.price_oracle_contract(),
            name,
            int(MINMAX[ix][0] / 365 / 86400),
            int(MINMAX[ix][1] / 365 / 86400),
        )

        salt = os.urandom(32)
        gauge = gauge_factory.deploy_gauge(vault, salt, GAUGE_FUNDER)
        gauges[ix] = gauge
        salts[ix] = salt

        print(name)
        print(f"Vault: {vault}")
        print(f"Salt: {salt.hex()}")
        print(f"Gauge: {gauge}")
        print()

    if "--fork" in sys.argv[1:]:
        boa.env.fork(NETWORK)
        boa.env.eoa = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
    else:
        boa.set_network_env(NETWORK)
        boa.env.add_account(babe_raw)
        boa.env._fork_try_prefetch_state = False

    gauge_factory_eth = boa.from_etherscan(
        gauge_factory.address, name="GaugeFactoryETH", api_key=ETHERSCAN_API_KEY
    )

    for i in INDEXES:
        print(f"Deploying a root gauge: {gauges[i]}")
        gauge_factory_eth.deploy_gauge(CHAIN_ID, salts[i])
