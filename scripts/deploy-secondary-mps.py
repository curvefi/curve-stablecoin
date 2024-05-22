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


FACTORY = "0xeA6876DDE9e3467564acBeE1Ed5bac88783205E0"
BORROWED_TOKEN = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"  # CRVUSD
U_0 = int(0.85e18)
LOW_RATIO = int(0.5e18)
HIGH_RATIO = int(3e18)
# WBTC, WETH, TBTC
AMMS = ["0x8eeDE294459EFaFf55d580bc95C98306Ab03F0C8", "0xb46aDcd1eA7E35C4EB801406C3E76E76e9a46EdF",
        "0x5338B1bf469651a5951ef618Fb5DeFbffaed7BE9"]


def account_load(fname):
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == '__main__':
    if '--fork' in sys.argv[1:]:
        boa.env.fork(NETWORK)
        boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
    else:
        boa.set_env(NetworkEnv(NETWORK))
        boa.env.add_account(account_load('babe'))
        boa.env._fork_try_prefetch_state = False

    policies = [
        boa.load('contracts/mpolicies/SecondaryMonetaryPolicy.vy',
                 FACTORY, amm, BORROWED_TOKEN, U_0, LOW_RATIO, HIGH_RATIO)
        for amm in AMMS
    ]

    for p in policies:
        print(p.address)
