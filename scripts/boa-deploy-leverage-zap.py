#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from networks import ETHEREUM, OPTIMISM, ARBITRUM, FRAXTAL, SONIC


def account_load(fname):
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)

CONSTANTS = {
    "mainnet": {
        "rpc": ETHEREUM,
        "lend_factory": "0xeA6876DDE9e3467564acBeE1Ed5bac88783205E0",
        "mint_factory": "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC",
        "routers": [
            "0x45312ea0eFf7E09C83CBE249fa1d7598c4C8cd4e",  # curve-js
            "0x0D05a7D3448512B78fa8A9e46c4872C88C4a0D05",  # odos
            "0xF75584eF6673aD213a685a1B58Cc0330B8eA22Cf",  # enso
            "0xa1c7a8360eb4049595a24d6919e74e105b409cb5",  # curve solver
        ]
    },
    "optimism": {
        "rpc": OPTIMISM,
        "lend_factory": "0x5EA8f3D674C70b020586933A0a5b250734798BeF",
        "mint_factory": None,
        "routers": [
            "0x0DCDED3545D565bA3B19E683431381007245d983",  # curve-js
            "0x0D05a7D3448512B78fa8A9e46c4872C88C4a0D05",  # odos
            "0xF75584eF6673aD213a685a1B58Cc0330B8eA22Cf",  # enso
        ]
    },
    "arbitrum": {
        "rpc": ARBITRUM,
        "lend_factory": "0xcaEC110C784c9DF37240a8Ce096D352A75922DeA",
        "mint_factory": None,
        "routers": [
            "0x2191718CD32d02B8E60BAdFFeA33E4B5DD9A0A0D",  # curve-js
            "0x0D05a7D3448512B78fa8A9e46c4872C88C4a0D05",  # odos
            "0xF75584eF6673aD213a685a1B58Cc0330B8eA22Cf",  # enso
            "0xa1c7a8360eb4049595a24d6919e74e105b409cb5",  # curve solver
        ]
    },
    "fraxtal": {
        "rpc": FRAXTAL,
        "lend_factory": "0xf3c9bdAB17B7016fBE3B77D17b1602A7db93ac66",
        "mint_factory": None,
        "routers": [
            "0x56C526b0159a258887e0d79ec3a80dfb940d0cD7",  # curve-js
            "0x0D05a7D3448512B78fa8A9e46c4872C88C4a0D05",  # odos
        ]
    },
    "sonic": {
        "rpc": SONIC,
        "lend_factory": "0x30d1859dad5a52ae03b6e259d1b48c4b12933993",
        "mint_factory": None,
        "routers": [
            "0x5eeE3091f747E60a045a2E715a4c71e600e31F6E",  # curve-js
            "0x0D05a7D3448512B78fa8A9e46c4872C88C4a0D05",  # odos
            "0xF75584eF6673aD213a685a1B58Cc0330B8eA22Cf",  # enso
        ]
    }
}

if __name__ == '__main__':
    args = sys.argv[1:]

    if '--network' not in args:
        raise Exception("You must pass '--network' arg")
    network = args[args.index('--network') + 1]
    if network not in CONSTANTS:
        raise Exception(f"{network} network is not supported")

    if '--factory' not in args:
        raise Exception("You must pass '--factory' arg (lend/mint)")
    factory_kind = args[args.index('--factory') + 1]
    if factory_kind not in ('lend', 'mint'):
        raise Exception(f"{factory_kind} factory is not supported (use lend/mint)")

    factory = CONSTANTS[network][f"{factory_kind}_factory"]
    if factory is None:
        raise Exception(f"{factory_kind} factory is not available on {network}")

    dry_run = '--dry-run' in args

    if dry_run:
        boa.fork(CONSTANTS[network]["rpc"])
    else:
        boa.set_network_env(CONSTANTS[network]["rpc"])
        boa.env.add_account(account_load('curve-deployer'))
    boa.env._fork_try_prefetch_state = False

    contract = boa.load('contracts/zaps/LeverageZap.vy', factory, CONSTANTS[network]["routers"])

    print(f"{'[dry-run] ' if dry_run else ''}Deployed at:", contract.address)
