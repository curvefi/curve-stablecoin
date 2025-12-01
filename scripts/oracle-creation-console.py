#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from networks import NETWORK


CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
TRICRV = "0x4eBdF703948ddCEA3B11f675B4D1Fba9d2414A14"
TRICRYPTO_LLAMA = "0x2889302a794dA87fBF1D6Db415C1492194663D13"


def account_load(fname):
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == "__main__":
    if "--fork" in sys.argv[1:]:
        boa.env.fork(NETWORK)
        boa.env.eoa = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
    else:
        boa.set_network_env(NETWORK)
        boa.env.add_account(account_load("babe"))
        boa.env._fork_try_prefetch_state = False

    oracle_factory = boa.load_partial(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRate.vy"
    )
    factory_agg = boa.load_partial(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRateWAgg.vy"
    )

    print(
        "================================================================================================================"
    )
    print("Usage:")
    print(
        ">> oracle_factory.deploy([0xpool1, 0xpool2], [borrowed_ix1, borrowed_ix2], [collateral_ix1, collateral_ix2])"
    )
    print(
        ">> factory_agg.deploy([0xpool1, 0xpool2], [borrowed_ix1, borrowed_ix2], [collateral_ix1, collateral_ix2], agg)"
    )
    print(
        "================================================================================================================"
    )
    print()

    import IPython

    IPython.embed()
