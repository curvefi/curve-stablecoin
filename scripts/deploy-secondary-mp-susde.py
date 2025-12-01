#!/usr/bin/env python3

# Deploed at: 0xf574cBeBBd549273aF82b42cD0230DE9eA6efEF7

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from boa.network import NetworkEnv


NETWORK = "http://localhost:8545"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


FACTORY = "0xeA6876DDE9e3467564acBeE1Ed5bac88783205E0"
BORROWED_TOKEN = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"  # CRVUSD
U_0 = int(0.85e18)
LOW_RATIO = int(0.35e18)
HIGH_RATIO = int(1.5e18)
CONTROLLER = "0x98Fc283d6636f6DCFf5a817A00Ac69A3ADd96907"
SUSDE = "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497"


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

    policy = boa.load(
        "curve_stablecoin/mpolicies/SusdeMonetaryPolicy.vy",
        FACTORY,
        SUSDE,
        BORROWED_TOKEN,
        U_0,
        LOW_RATIO,
        HIGH_RATIO,
        0,
    )

    print(policy.raw_susde_apr() / 1e18)
    print(policy.rate(CONTROLLER) * 86400 * 365 / 1e18)
    policy.rate_write()
