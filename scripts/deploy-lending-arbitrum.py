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

from networks import NETWORK, ARBITRUM


ADMIN = "0x452030a5D962d37D97A9D65487663cD5fd9C2B32"  # L2 ownership admin
GAUGE_FACTORY = "0xabC000d88f23Bb45525E447528DBF656A9D55bf5"  # Arbitrum gauge factory has also the same address on L1
CRVUSD = "0x498Bf2B1e120FeD3ad3D42EA2165E9b73f99C1e5"  # crvUSD-arbi
GAUGE_FUNDER = "0x7a16fF8270133F063aAb6C9977183D9e72835428"
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
        boa.set_network_env(ARBITRUM)
        boa.env.add_account(account_load('babe'))
        boa.env._fork_try_prefetch_state = False

    amm_impl = boa.load_partial('contracts/AMM.vy').deploy_as_blueprint()
    controller_impl = boa.load_partial('contracts/Controller.vy').deploy_as_blueprint()
    vault_impl = boa.load('contracts/lending/Vault.vy')
    price_oracle_impl = boa.load_partial('contracts/price_oracles/L2/CryptoFromPoolArbitrum.vy').deploy_as_blueprint()
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
        # Deploy WETH long market
        name = "WETH-long"
        oracle_pool = "0x82670f35306253222F8a165869B28c64739ac62e"  # Tricrypto-crvUSD (Arbitrum)
        collateral = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"   # WETH
        borrowed = CRVUSD
        A = 70
        fee = int(0.006 * 1e18)
        borrowing_discount = int(0.07 * 1e18)
        liquidation_discount = int(0.04 * 1e18)
        min_borrow_rate = 2 * 10**16 // (365 * 86400)  # 2%
        max_borrow_rate = 50 * 10**16 // (365 * 86400)  # 50%
        vault_weth = factory.create_from_pool(borrowed, collateral, A, fee, borrowing_discount, liquidation_discount,
                                              oracle_pool, name, min_borrow_rate, max_borrow_rate)
        salt_weth = os.urandom(32)
        gauge_weth = gauge_factory.deploy_gauge(vault_weth, salt_weth, GAUGE_FUNDER)
        print(f"Vault {name}: {vault_weth}, gauge: {gauge_weth}, salt: {salt_weth.hex()}")

        # Deploy wBTC long market
        name = "wBTC-long"
        oracle_pool = "0x82670f35306253222F8a165869B28c64739ac62e"  # Tricrypto-crvUSD (Arbitrum)
        collateral = "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f"   # wBTC
        borrowed = CRVUSD
        A = 75
        fee = int(0.0015 * 1e18)
        borrowing_discount = int(0.065 * 1e18)
        liquidation_discount = int(0.035 * 1e18)
        min_borrow_rate = 2 * 10**16 // (365 * 86400)  # 2%
        max_borrow_rate = 50 * 10**16 // (365 * 86400)  # 50%
        vault_wbtc = factory.create_from_pool(borrowed, collateral, A, fee, borrowing_discount, liquidation_discount,
                                              oracle_pool, name, min_borrow_rate, max_borrow_rate)
        salt_wbtc = os.urandom(32)
        gauge_wbtc = gauge_factory.deploy_gauge(vault_wbtc, salt_wbtc, GAUGE_FUNDER)
        print(f"Vault {name}: {vault_wbtc}, gauge: {gauge_wbtc}, salt: {salt_wbtc.hex()}")

        if '--fork' in sys.argv[1:]:
            boa.env.fork(NETWORK)
            boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
        else:
            boa.set_network_env(NETWORK)
            boa.env.add_account(account_load('babe'))
            boa.env._fork_try_prefetch_state = False

        gauge_factory_eth = ABIContractFactory.from_abi_dict(GAUGE_FACTORY_ABI_ETH).at(GAUGE_FACTORY)

        gauge_factory_eth.deploy_gauge(CHAIN_ID, salt_weth)
        gauge_factory_eth.deploy_gauge(CHAIN_ID, salt_wbtc)

    if '--hardhat' in sys.argv[1:]:
        hardhat.wait()
