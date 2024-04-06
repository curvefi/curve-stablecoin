#!/usr/bin/env python3

# Deployed at:
# https://arbiscan.io/address/0x6EFE6D76f0dAA3E01b690f667087d050F98e8835#readContract

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from networks import ARBITRUM


POOLS = ["0x5f0985A8aAd85e82fD592a23Cc0501e4345fb18c", "0x82670f35306253222F8a165869B28c64739ac62e"]  # FXN/WETH, Tricrypto(crvUSD+WBTC+WETH)
BORROWED_IXS = [0, 0]
COLLATERAL_IXS = [1, 2]


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

    contract = boa.load(
        'contracts/price_oracles/L2/CryptoFromPoolsRateArbitrum.vy',
        POOLS, BORROWED_IXS, COLLATERAL_IXS)

    print('Deployed at:', contract.address)
