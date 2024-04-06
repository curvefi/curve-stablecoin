#!/usr/bin/env python3

# Deployed vault: 0xb56369a6519F84C6fD92644D421273618B8d62B0

import boa
import json
import os
import sys
from time import sleep
import subprocess
from getpass import getpass
from eth_account import account
from boa.contracts.abi.abi_contract import ABIContractFactory

from networks import NETWORK, ARBITRUM


FACTORY = "0xcaEC110C784c9DF37240a8Ce096D352A75922DeA"
GAUGE_FACTORY = "0xabC000d88f23Bb45525E447528DBF656A9D55bf5"  # Arbitrum gauge factory has also the same address on L1
CRVUSD = "0x498Bf2B1e120FeD3ad3D42EA2165E9b73f99C1e5"  # crvUSD-arbi
GAUGE_FUNDER = "0x7a16fF8270133F063aAb6C9977183D9e72835428"
ORACLE = "0x6EFE6D76f0dAA3E01b690f667087d050F98e8835"
HARDHAT_COMMAND = ["npx", "hardhat", "node", "--fork", ARBITRUM, "--port", "8545"]

CHAIN_ID = 42161
GAUGE_FACTORY_ABI = [
    {"stateMutability": "nonpayable",
     "type": "function",
     "name": "deploy_gauge",
     "inputs": [{"name": "_lp_token", "type": "address"}, {"name": "_salt", "type": "bytes32"}, {"name": "_manager", "type": "address"}],
     "outputs": [{"name": "", "type": "address"}]},
]
GAUGE_FACTORY_ABI_ETH = [
    {"stateMutability": "payable",
     "type": "function",
     "name": "deploy_gauge",
     "inputs": [{"name": "_chain_id", "type": "uint256"}, {"name": "_salt", "type": "bytes32"}],
     "outputs": [{"name": "", "type": "address"}],
     "gas": 165352}
]


def account_load(fname):
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == '__main__':
    if '--hardhat' in sys.argv[1:]:
        hardhat = subprocess.Popen(HARDHAT_COMMAND)
        sleep(5)

    if '--fork' in sys.argv[1:]:
        boa.env.fork(ARBITRUM)
        boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
    else:
        babe = account_load('babe')
        boa.set_network_env(ARBITRUM)
        boa.env.add_account(babe)
        boa.env._fork_try_prefetch_state = False

    gauge_factory = ABIContractFactory.from_abi_dict(GAUGE_FACTORY_ABI).at(GAUGE_FACTORY)

    factory = boa.load_partial('contracts/lending/OneWayLendingFactoryL2.vy').at(FACTORY)

    # Deploy FXN long market
    name = "FXN-long"
    collateral = "0x179F38f78346F5942E95C5C59CB1da7F55Cf7CAd"   # FXN
    borrowed = CRVUSD
    A = 21
    fee = int(0.015 * 1e18)
    borrowing_discount = int(0.17 * 1e18)
    liquidation_discount = int(0.14 * 1e18)
    min_borrow_rate = 5 * 10**15 // (365 * 86400)  # 0.5%
    max_borrow_rate = 60 * 10**16 // (365 * 86400)  # 60%
    vault_fxn = factory.create(borrowed, collateral, A, fee, borrowing_discount, liquidation_discount,
                               ORACLE, name, min_borrow_rate, max_borrow_rate)
    salt_fxn = os.urandom(32)
    gauge_factory.deploy_gauge(vault_fxn, salt_fxn, GAUGE_FUNDER)
    print(f"Vault {name}: {vault_fxn}, salt: {salt_fxn.hex()}")

    if '--fork' in sys.argv[1:]:
        boa.env.fork(NETWORK)
        boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
    else:
        boa.set_network_env(NETWORK)
        boa.env.add_account(babe)
        boa.env._fork_try_prefetch_state = False

    gauge_factory_eth = ABIContractFactory.from_abi_dict(GAUGE_FACTORY_ABI_ETH).at(GAUGE_FACTORY)

    gauge_factory_eth.deploy_gauge(CHAIN_ID, salt_fxn)

    if '--hardhat' in sys.argv[1:]:
        hardhat.wait()
