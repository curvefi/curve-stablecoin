#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from networks import ETHEREUM, ARBITRUM


def account_load(fname):
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


CONSTANTS = {
    "mainnet": {
        "rpc": ETHEREUM,
        "router_1inch": "0x111111125421ca6dc452d289314280a0f8842a65",
        "factories": [
            "0xeA6876DDE9e3467564acBeE1Ed5bac88783205E0",
            "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC",
        ],  # LlamaLend, crvUSD
    },
    "arbitrum": {
        "rpc": ARBITRUM,
        "router_1inch": "0x111111125421ca6dc452d289314280a0f8842a65",
        "factories": ["0xcaEC110C784c9DF37240a8Ce096D352A75922DeA"],
    },
}

if __name__ == "__main__":
    if "--network" not in sys.argv[1:]:
        raise Exception("You must pass '--network' arg")
    if sys.argv[2] not in CONSTANTS:
        raise Exception(f"{sys.argv[2]} network is not supported")

    network = sys.argv[2]
    boa.set_network_env(CONSTANTS[network]["rpc"])
    boa.env.add_account(account_load("curve-deployer"))
    boa.env._fork_try_prefetch_state = False

    contract = boa.load(
        "contracts/zaps/LeverageZap.vy",
        CONSTANTS[network]["router_1inch"],
        CONSTANTS[network]["factories"],
    )

    print("Deployed at:", contract.address)
