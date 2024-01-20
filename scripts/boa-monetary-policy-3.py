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
ADMIN = "0x40907540d8a6C65c637785e8f8B742ae6b0b9968"

POLICIES = {
    'staked': {
        'rate0': 4756468797,
        'controllers': [
            "0x100daa78fc509db39ef7d04de0c1abd299f4c6ce",  # wstETH
            "0xec0820efafc41d8943ee8de495fc9ba8495b15cf",  # sfrxETHv2
        ]
    },
    'plain': {
        'rate0': 3488077118,
        'controllers': [
            "0x4e59541306910ad6dc1dac0ac9dfb29bd9f15c67",  # WBTC
            "0xa920de414ea4ab66b97da1bfe9e6eca7d4219635",  # ETH
            "0x1c91da0223c763d2e0173243eadaa0a2ea47e704",  # tBTC
        ]
    },
}

STABLE_ORACLE = "0x18672b1b0c623a30089A280Ed9256379fb0E4E62"
FACTORY = "0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"
PEG_KEEPERS = [
    "0xaA346781dDD7009caa644A4980f044C50cD2ae22",
    "0xE7cd2b4EB1d98CD6a4A48B6071D46401Ac7DC5C8",
    "0x6B765d07cf966c745B340AdCa67749fE75B5c345",
    "0x1ef89Ed0eDd93D1EC09E4c07373f69C49f4dcCae"
]


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

    factory = boa.load_partial('contracts/ControllerFactory.vy').at(FACTORY)

    for policy in POLICIES:
        rate0 = POLICIES[policy]['rate0']
        contract = boa.load(
            'contracts/mpolicies/AggMonetaryPolicy3.vy',
            ADMIN,
            STABLE_ORACLE,
            FACTORY,
            PEG_KEEPERS + [ZERO_ADDRESS],
            rate0,
            2 * 10**16,  # Sigma 2%
            10 * 10**16)  # Target debt fraction 10%

        print(f'Policy {policy} deployed at {contract.address}')

        for controller in POLICIES[policy]['controllers']:
            print('Saving candle for:', controller)
            contract.rate_write(controller, gas=10**6)

        contract.rate_write(gas=10**6)
        print()
