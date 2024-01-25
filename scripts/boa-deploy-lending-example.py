#!/usr/bin/env python3

import boa
import json
import os
import sys
from time import sleep
import subprocess
from getpass import getpass
from eth_account import account
from boa.network import NetworkEnv


NETWORK = "http://localhost:8545"
ADMIN = "0x40907540d8a6C65c637785e8f8B742ae6b0b9968"
CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
HARDHAT_COMMAND = ["npx", "hardhat", "node", "--fork", "https://eth.drpc.org", "--port", "8545"]


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
        boa.env.fork(NETWORK)
        boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
    else:
        boa.set_env(NetworkEnv(NETWORK))
        boa.env.add_account(account_load('babe'))
        boa.env._fork_try_prefetch_state = False

    amm_impl = boa.load_partial('contracts/AMM.vy').deploy_as_blueprint()
    controller_impl = boa.load_partial('contracts/Controller.vy').deploy_as_blueprint()
    vault_impl = boa.load('contracts/lending/Vault.vy')
    price_oracle_impl = boa.load_partial('contracts/price_oracles/CryptoFromPool.vy').deploy_as_blueprint()
    mpolicy_impl = boa.load_partial('contracts/mpolicies/SemilogMonetaryPolicy.vy').deploy_as_blueprint()

    factory = boa.load(
            'contracts/lending/OneWayLendingFactory.vy',
            CRVUSD,
            amm_impl, controller_impl, vault_impl,
            price_oracle_impl, mpolicy_impl,
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

    # Deploying an example
    CRV = "0xd533a949740bb3306d119cc777fa900ba034cd52"
    TRICRV_POOL = "0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14"
    factory.create_from_pool(CRVUSD, CRV, 100, int(0.006 * 1e18), 9 * 10**16, 6 * 10**16, TRICRV_POOL)

    import IPython
    IPython.embed()

    if '--hardhat' in sys.argv[1:]:
        hardhat.wait()
