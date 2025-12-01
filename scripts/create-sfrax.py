#!/usr/bin/env python3

# Vault: 0xd0c183C9339e73D7c9146D48E1111d1FBEe2D6f9
# Gauge: 0xDFF0ed66fdDCC440FB3aDFB2f12029925799979c
# Oracle: 0xAC8A4D55c1d6Ea3F84A6c868f2b5a5Ec3CeF2800

# Deployed addresses
# WETH:
# Vault: 0x8fb1c7AEDcbBc1222325C39dd5c1D2d23420CAe3
# Gauge: 0xF3F6D6d412a77b680ec3a5E35EbB11BbEC319739
# Monetary policy (to replace with): 0x627bB157eBc0B77aD9F990DD2aD75878603abf08

# WSTETH:
# Vault: 0x21CF1c5Dc48C603b89907FE6a7AE83EA5e3709aF
# Gauge: 0x0621982CdA4fD4041964e91AF4080583C5F099e1
# Policy: 0xbc7507bEA8d7bcb49f511cf59651B5114e6E7667

import boa
import json
import os
import sys
from time import sleep
from getpass import getpass
from eth_account import account
from networks import NETWORK

# Deployment log:
# Vault: 0xc687141c18F20f7Ba405e45328825579fDdD3195
# Gauge: 0xEAED59025d6Cf575238A9B4905aCa11E000BaAD0
# Oracle: 0xFb230bC3De97eE43d2501bCaab9A50bba9B69E1B

FACTORY = "0xeA6876DDE9e3467564acBeE1Ed5bac88783205E0"
CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
AGG = "0x18672b1b0c623a30089A280Ed9256379fb0E4E62"
FRAX_POOL = "0x0CD6f267b2086bea681E922E19D40512511BE538"
SFRAX = "0xA663B02CF0a4b149d2aD41910CB81e23e1c41c32"


min_rate = int(0.005e18 / (365 * 86400))
max_rate = int(0.25e18 / (365 * 86400))


def account_load(fname):
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == "__main__":
    if "--fork" in sys.argv[1:]:
        boa.env.fork(NETWORK)
        boa.env.eoa = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
    else:
        boa.set_network_env(NETWORK)
        boa.env.add_account(account_load("babe"))
        boa.env._fork_try_prefetch_state = False

    factory = boa.load_partial("curve_stablecoin/lending/OneWayLendingFactory.vy").at(
        FACTORY
    )
    oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolVaultWAgg.vy",
        FRAX_POOL,
        2,  # Number of coins
        1,  # Borrowed index
        0,  # Collateral index
        SFRAX,
        AGG,
    )
    sleep(10)
    oracle.price_w()
    sleep(10)

    vault = factory.create(
        CRVUSD,
        SFRAX,
        285,  # A
        int(0.002e18),  # fee
        int(0.013e18),  # loan_discount
        int(0.010e18),  # liq_discount
        oracle.address,
        "sfrax-long",
        min_rate,
        max_rate,
    )
    sleep(10)
    gauge = factory.deploy_gauge(vault)
    sleep(10)

    print(f"Vault: {vault}")
    print(f"Gauge: {gauge}")
    print(f"Oracle: {oracle.address}")
    print(f"Oracle price: {oracle.price() / 1e18}")
    print()
