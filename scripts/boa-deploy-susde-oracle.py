#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from boa.network import NetworkEnv


NETWORK = "http://localhost:8545"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

POOL = "0xF55B0f6F2Da5ffDDb104b58a60F2862745960442"
BORROWED_IX = 1
COLLATERAL_IX = 0
VAULT = "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497"


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
        boa.set_env(NetworkEnv(NETWORK))
        boa.env.add_account(account_load("babe"))
        boa.env._fork_try_prefetch_state = False

    contract = boa.load(
        "contracts/price_oracles/CryptoFromPoolVault_noncurve.vy",
        POOL,
        2,
        BORROWED_IX,
        COLLATERAL_IX,
        VAULT,
    )

    print("Deployed at:", contract.address)
