#!/usr/bin/env python3

import boa
import json
import os
from getpass import getpass
from eth_account import account
from networks import ETHEREUM

CRVUSD_FACTORY = "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"


def account_load(fname):
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == '__main__':
    boa.set_network_env(ETHEREUM)
    boa.env.add_account(account_load('babe'))
    boa.env._fork_try_prefetch_state = False

    contract = boa.load('contracts/flashloan/FlashLender.vy', CRVUSD_FACTORY)

    print('Deployed at:', contract.address)
