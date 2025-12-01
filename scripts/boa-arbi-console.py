#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from networks import ARBITRUM


FACTORY = "0xcaEC110C784c9DF37240a8Ce096D352A75922DeA"


def account_load(fname):
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == "__main__":
    if "--fork" in sys.argv[1:]:
        boa.env.fork(ARBITRUM)
        boa.env.eoa = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
    else:
        boa.set_network_env(ARBITRUM)
        boa.env.add_account(account_load("babe"))
        boa.env._fork_try_prefetch_state = False

    oracle_code = boa.load_partial(
        "curve_stablecoin/price_oracles/L2/CryptoFromPoolArbitrum.vy"
    )
    agg_oracle_code = boa.load_partial(
        "curve_stablecoin/price_oracles/L2/CryptoFromPoolsRateArbitrumWAgg.vy"
    )
    factory = boa.load_partial(
        "curve_stablecoin/lending/deprecated/OneWayLendingFactoryL2.vy"
    ).at(FACTORY)

    import IPython

    IPython.embed()
