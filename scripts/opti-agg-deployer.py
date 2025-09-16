#!/usr/bin/env python3

# Deployed aggregator:
# https://optimistic.etherscan.io/address/0x534a909f456dfae903d7ea6927a1c7646099b02e#code

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from networks import OPTIMISM


crvusd = "0xC52D7F23a2e460248Db6eE192Cb23dD12bDDCbf6"
sigma = int(0.001 * 1e18)

pools = [
    "0x03771e24b7C9172d163Bf447490B142a15be3485",  # USDC
    "0xD1b30BA128573fcd7D141C8A987961b40e047BB6",  # USDT
    "0x05FA06D4Fb883F67f1cfEA0889edBff9e8358101",  # USDC.e
]

admin = "0x28c4A1Fa47EEE9226F8dE7D6AF0a41C62Ca98267"


def account_load(fname):
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == "__main__":
    if "--fork" in sys.argv[1:]:
        boa.env.fork(OPTIMISM)
        boa.env.eoa = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
    else:
        boa.set_network_env(OPTIMISM)
        boa.env.add_account(account_load("babe"))
        boa.env._fork_try_prefetch_state = False

    agg_factory = boa.load_partial("contracts/price_oracles/AggregateStablePrice3.vy")
    agg = agg_factory.deploy(crvusd, sigma, boa.env.eoa)

    for pool in pools:
        agg.add_price_pair(pool, gas=10**6)

    agg.set_admin(admin, gas=10**6)

    print(agg.address)
