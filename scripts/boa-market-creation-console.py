#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from networks import NETWORK


FACTORY = "0xeA6876DDE9e3467564acBeE1Ed5bac88783205E0"
CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
TBTC = "0x18084fbA666a33d37592fA2633fD49a74DD93a88"
TRICRV = "0x4eBdF703948ddCEA3B11f675B4D1Fba9d2414A14"
TRICRYPTO_LLAMA = "0x2889302a794dA87fBF1D6Db415C1492194663D13"
WBTC = "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"
PUFETH = "0xD9A442856C234a39a81a089C06451EBAa4306a72"
EZETH = "0xbf5495Efe5DB9ce00f80364C8B423567e58d2110"
USDE = "0x4c9EDD5852cd905f086C759E8383e09bff1E68B3"
SUSDE = "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497"
WEETH = "0xCd5fE23C85820F7B72D0926FC9b05b43E359b7ee"
FXS = "0x3432B6A60D23Ca0dFCa7761B7ab56459D9C964D0"


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
        boa.set_network_env(NETWORK)
        boa.env.add_account(account_load('babe'))
        boa.env._fork_try_prefetch_state = False

    factory = boa.load_partial('contracts/lending/OneWayLendingFactory.vy').at(FACTORY)

    import IPython
    IPython.embed()
