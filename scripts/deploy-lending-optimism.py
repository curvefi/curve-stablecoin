#!/usr/bin/env python3

import boa
import json
import os
import sys
from time import sleep
import subprocess
from getpass import getpass
from eth_account import account
from boa.contracts.abi.abi_contract import ABIContractFactory

from networks import NETWORK, OPTIMISM


ADMIN = "0x28c4A1Fa47EEE9226F8dE7D6AF0a41C62Ca98267"  # L2 ownership admin
GAUGE_FACTORY = "0xabC000d88f23Bb45525E447528DBF656A9D55bf5"  # Optimism gauge factory has also the same address on L1
CRVUSD = "0xC52D7F23a2e460248Db6eE192Cb23dD12bDDCbf6"  # crvUSD-opti
GAUGE_FUNDER = "0x7a16fF8270133F063aAb6C9977183D9e72835428"
HARDHAT_COMMAND = ["npx", "hardhat", "node", "--fork", OPTIMISM, "--port", "8545"]

AGG = "0x534a909f456dfae903d7ea6927a1c7646099b02e"

# ORACLES = [
#     ('VELO', '0x0f2Ed59657e391746C1a097BDa98F2aBb94b1120')
# ]

MARKET_PARAMS = [
    ('ETH', {
        'collateral': '0x4200000000000000000000000000000000000006',
        'A': 70,
        'fee': int(0.006e18),
        'borrowing_discount': int(0.07e18),
        'liquidation_discount': int(0.04e18),
        'min_borrow_rate': 2 * 10**16 // (365 * 86400),
        'max_borrow_rate': 30 * 10**16 // (365 * 86400),
        'oracle_contract': '0x92577943c7aC4accb35288aB2CC84D75feC330aF',
        'supply_limit': 2**256-1
     }),
    ('wstETH', {
        'collateral': '0x1F32b1c2345538c0c6f582fCB022739c4A194Ebb',
        'A': 70,
        'fee': int(0.006e18),
        'borrowing_discount': int(0.07e18),
        'liquidation_discount': int(0.04e18),
        'min_borrow_rate': 2 * 10**16 // (365 * 86400),
        'max_borrow_rate': 30 * 10**16 // (365 * 86400),
        'oracle_contract': '0x44343B1B95BaA53eC561F8d7B357155B89507077',
        'supply_limit': 2**256-1
     }),
    ('WBTC', {
        'collateral': '0x68f180fcCe6836688e9084f035309E29Bf0A2095',
        'A': 70,
        'fee': int(0.006e18),
        'borrowing_discount': int(0.065e18),
        'liquidation_discount': int(0.035e18),
        'min_borrow_rate': 2 * 10**16 // (365 * 86400),
        'max_borrow_rate': 30 * 10**16 // (365 * 86400),
        'oracle_contract': '0xEc12C072d9ABdf3F058C8B17169eED334fC1dE58',
        'supply_limit': 2**256-1
     }),
    ('OP', {
        'collateral': '0x4200000000000000000000000000000000000042',
        'A': 22,
        'fee': int(0.006e18),
        'borrowing_discount': int(0.155e18),
        'liquidation_discount': int(0.125e18),
        'min_borrow_rate': 2 * 10**16 // (365 * 86400),
        'max_borrow_rate': 30 * 10**16 // (365 * 86400),
        'oracle_contract': '0x3Fa8ebd5d16445b42e0b6A54678718C94eA99aBC',
        'supply_limit': 15 * 10**6 * 10**18
    }),
    ('CRV', {
        'collateral': '0x0994206dfE8De6Ec6920FF4D779B0d950605Fb53',
        'A': 22,
        'fee': int(0.006e18),
        'borrowing_discount': int(0.155e18),
        'liquidation_discount': int(0.125e18),
        'min_borrow_rate': 2 * 10**16 // (365 * 86400),
        'max_borrow_rate': 30 * 10**16 // (365 * 86400),
        'oracle_contract': '0x2016f1AaE491438E6EA908e30b60dAeb56ac185c',
        'supply_limit': 15 * 10**6 * 10**18
    })
]

CHAIN_ID = 10
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
        boa.env.fork(OPTIMISM)
        boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
    else:
        babe = account_load('babe')
        boa.set_network_env(OPTIMISM)
        boa.env.add_account(babe)
        boa.env._fork_try_prefetch_state = False

    amm_impl = boa.load_partial('contracts/AMM.vy').deploy_as_blueprint()
    controller_impl = boa.load_partial('contracts/Controller.vy').deploy_as_blueprint()
    vault_impl = boa.load('contracts/lending/Vault.vy')
    price_oracle_impl = boa.load_partial('contracts/price_oracles/L2/CryptoFromPoolOptimismWAgg.vy').deploy_as_blueprint()
    mpolicy_impl = boa.load_partial('contracts/mpolicies/SemilogMonetaryPolicy.vy').deploy_as_blueprint()
    gauge_factory = ABIContractFactory.from_abi_dict(GAUGE_FACTORY_ABI).at(GAUGE_FACTORY)

    factory = boa.load(
            'contracts/lending/OneWayLendingFactoryL2.vy',
            CRVUSD,
            amm_impl, controller_impl, vault_impl,
            price_oracle_impl, mpolicy_impl, GAUGE_FACTORY,
            ADMIN)

    print('Deployed contracts:')
    print('==========================')
    print('AMM implementation:', amm_impl.address)
    print('Controller implementation:', controller_impl.address)
    print('Vault implementation:', vault_impl.address)
    print('Pool price oracle implementation:', price_oracle_impl.address)
    print('Monetary Policy implementation:', mpolicy_impl.address)
    print('Factory:', factory.address)
    print('==========================')

    if '--markets' in sys.argv[1:]:
        for name, p in MARKET_PARAMS:
            vault = factory.create(
                CRVUSD, p['collateral'],
                p['A'], p['fee'], p['borrowing_discount'], p['liquidation_discount'],
                p['oracle_contract'], name + '-long',
                p['min_borrow_rate'], p['max_borrow_rate'], p['supply_limit'])
            salt = os.urandom(32)
            gauge_factory.deploy_gauge(vault, salt, GAUGE_FUNDER)
            print(f"Vault {name}: {vault}, salt: {salt.hex()}")
            p['salt'] = salt

        if '--fork' in sys.argv[1:]:
            boa.env.fork(NETWORK)
            boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
        else:
            boa.set_network_env(NETWORK)
            boa.env.add_account(babe)
            boa.env._fork_try_prefetch_state = False

        gauge_factory_eth = ABIContractFactory.from_abi_dict(GAUGE_FACTORY_ABI_ETH).at(GAUGE_FACTORY)

        for name, p in MARKET_PARAMS:
            if '--fork' not in sys.argv[1:]:
                sleep(30)  # RPCs on Ethereum can change the node, so need to sleep to not fail
            salt = p['salt']
            print(f'Deploying on Ethereum with salt: {salt.hex()}')
            gauge_factory_eth.deploy_gauge(CHAIN_ID, salt)

    if '--hardhat' in sys.argv[1:]:
        hardhat.wait()
