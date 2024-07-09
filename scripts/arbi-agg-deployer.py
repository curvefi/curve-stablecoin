#!/usr/bin/env python3

# Deployed aggregator:
# https://arbiscan.io/address/0x44a4FdFb626Ce98e36396d491833606309520330#readContract

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from networks import ARBITRUM


crvusd = "0x498Bf2B1e120FeD3ad3D42EA2165E9b73f99C1e5"
sigma = int(0.001 * 1e18)

pools = [
    "0xec090cf6DD891D2d014beA6edAda6e05E025D93d",  # USDC
    "0x73aF1150F265419Ef8a5DB41908B700C32D49135",  # USDT
    "0x3aDf984c937FA6846E5a24E0A68521Bdaf767cE1",  # USDC.e
    "0x2FE7AE43591E534C256A1594D326e5779E302Ff4"   # FRAX
]

admin = "0x452030a5D962d37D97A9D65487663cD5fd9C2B32"


def account_load(fname):
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == '__main__':
    if '--fork' in sys.argv[1:]:
        boa.env.fork(ARBITRUM)
        boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
    else:
        boa.set_network_env(ARBITRUM)
        boa.env.add_account(account_load('babe'))
        boa.env._fork_try_prefetch_state = False

    agg_factory = boa.load_partial('contracts/price_oracles/AggregateStablePrice3.vy')
    agg = agg_factory.deploy(crvusd, sigma, boa.env.eoa)

    for pool in pools:
        agg.add_price_pair(pool)

    agg.set_admin(admin)

    print(agg.address)
