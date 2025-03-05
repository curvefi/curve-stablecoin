#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from networks import ETHEREUM, ARBITRUM, FRAXTAL, SONIC


def account_load(fname):
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)

CONSTANTS = {
    "mainnet": {
        "rpc": ETHEREUM,
        "router_odos": "0xCf5540fFFCdC3d510B18bFcA6d2b9987b0772559",
        "factories": ["0xeA6876DDE9e3467564acBeE1Ed5bac88783205E0", "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"],  # LlamaLend, crvUSD
    },
    "arbitrum": {
        "rpc": ARBITRUM,
        "router_odos": "0xa669e7A0d4b3e4Fa48af2dE86BD4CD7126Be4e13",
        "factories": ["0xcaEC110C784c9DF37240a8Ce096D352A75922DeA"],
    },
    "fraxtal": {
        "rpc": FRAXTAL,
        "router_odos": "0x56c85a254DD12eE8D9C04049a4ab62769Ce98210",
        "factories": ["0xf3c9bdAB17B7016fBE3B77D17b1602A7db93ac66"],
    },
    "sonic": {
        "rpc": SONIC,
        "router_odos": "0xaC041Df48dF9791B0654f1Dbbf2CC8450C5f2e9D",
        "factories": ["0x30d1859dad5a52ae03b6e259d1b48c4b12933993"],
    }
}

if __name__ == '__main__':
    if '--network' not in sys.argv[1:]:
        raise Exception("You must pass '--network' arg")
    if sys.argv[2] not in CONSTANTS:
        raise Exception(f"{sys.argv[2]} network is not supported")

    network = sys.argv[2]
    boa.set_network_env(CONSTANTS[network]["rpc"])
    boa.env.add_account(account_load('curve-deployer'))
    boa.env._fork_try_prefetch_state = False

    contract = boa.load('contracts/zaps/LeverageZap.vy',
                        CONSTANTS[network]["router_odos"], CONSTANTS[network]["factories"])

    print('Deployed at:', contract.address)
