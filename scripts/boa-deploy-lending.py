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
    gauge_impl = boa.load_partial('contracts/lending/LiquidityGauge.vy').deploy_as_blueprint()

    factory = boa.load(
            'contracts/lending/OneWayLendingFactory.vy',
            CRVUSD,
            amm_impl, controller_impl, vault_impl,
            price_oracle_impl, mpolicy_impl, gauge_impl,
            ADMIN)

    print('Deployed contracts:')
    print('==========================')
    print('AMM implementation:', amm_impl.address)
    print('Controller implementation:', controller_impl.address)
    print('Vault implementation:', vault_impl.address)
    print('Pool price oracle implementation:', price_oracle_impl.address)
    print('Monetary Policy implementation:', mpolicy_impl.address)
    print('Gauge implementation:', gauge_impl.address)
    print('Factory:', factory.address)
    print('==========================')

    if '--markets' in sys.argv[1:]:
        # Deploy wstETH long market
        name = "wstETH-long"
        oracle_pool = "0x2889302a794dA87fBF1D6Db415C1492194663D13"  # TricryptoLLAMA
        collateral = "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0"   # wstETH
        borrowed = CRVUSD
        A = 100
        fee = int(0.005 * 1e18)
        borrowing_discount = int(0.09 * 1e18)
        liquidation_discount = int(0.06 * 1e18)
        min_borrow_rate = 5 * 10**15 // (365 * 86400)  # 0.5%
        max_borrow_rate = 25 * 10**16 // (365 * 86400)  # 25%
        vault = factory.create_from_pool(borrowed, collateral, A, fee, borrowing_discount, liquidation_discount,
                                         oracle_pool, name, min_borrow_rate, max_borrow_rate)
        gauge = factory.deploy_gauge(vault)
        print(f"Vault {name}: {vault}, gauge: {gauge}")

        # Deploy CRV long market
        name = "CRV-long"
        oracle_pool = "0x4eBdF703948ddCEA3B11f675B4D1Fba9d2414A14"  # TriCRV
        CRV = "0xD533a949740bb3306d119CC777fa900bA034cd52"
        collateral = CRV
        borrowed = CRVUSD
        A = 50
        fee = int(0.006 * 1e18)
        borrowing_discount = int(0.14 * 1e18)
        liquidation_discount = int(0.11 * 1e18)
        vault = factory.create_from_pool(borrowed, collateral, A, fee, borrowing_discount, liquidation_discount,
                                         oracle_pool, name)
        gauge = factory.deploy_gauge(vault)
        print(f"Vault {name}: {vault}, gauge: {gauge}")

        # Deploy CRV short market
        name = "CRV-short"
        oracle_pool = "0x4eBdF703948ddCEA3B11f675B4D1Fba9d2414A14"  # TriCRV
        collateral = CRVUSD
        borrowed = CRV
        vault = factory.create_from_pool(borrowed, collateral, A, fee, borrowing_discount, liquidation_discount,
                                         oracle_pool, name)
        gauge = factory.deploy_gauge(vault)
        print(f"Vault {name}: {vault}, gauge: {gauge}")

    if '--hardhat' in sys.argv[1:]:
        hardhat.wait()
