#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from boa.network import NetworkEnv


NETWORK = "http://localhost:8545"


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

    amm_impl = boa.load_partial("contracts/AMM.vy").deploy_as_blueprint()
    controller_impl = boa.load_partial("contracts/Controller.vy").deploy_as_blueprint()

    print("Deployed contracts:")
    print("==========================")
    print("AMM implementation:", amm_impl.address)
    print("Controller implementation:", controller_impl.address)
    print("==========================")
