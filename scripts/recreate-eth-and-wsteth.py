#!/usr/bin/env python3

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
from getpass import getpass
from eth_account import account
from networks import NETWORK, ETHERSCAN_API_KEY


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
WSTETH = "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0"


WSTETH_INDEX = 0
WETH_INDEX = 1
OLD_WSTETH_CONTROLLER = "0x1E0165DbD2019441aB7927C018701f3138114D71"
OLD_WETH_CONTROLLER = "0xaade9230AA9161880E13a38C83400d3D1995267b"
WETH_AMM = "0x1681195C176239ac5E72d9aeBaCf5b2492E0C4ee"

target_utilization = int(0.85e18)
low_ratio = int(0.35e18)
high_ratio = int(3e18)


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

    factory = boa.load_partial("contracts/lending/OneWayLendingFactory.vy").at(FACTORY)
    policy_deployer = boa.load_partial("contracts/mpolicies/SecondaryMonetaryPolicy.vy")

    # for ix in [WETH_INDEX, WSTETH_INDEX]:
    for ix in [WSTETH_INDEX]:
        if ix == WSTETH_INDEX:
            rate_shift = int(0.03e18 / 365 / 86400)
        else:
            rate_shift = 0
        old_controller = boa.from_etherscan(
            factory.controllers(ix), name="Controller", api_key=ETHERSCAN_API_KEY
        )
        old_amm = boa.from_etherscan(
            old_controller.amm(), name="AMM", api_key=ETHERSCAN_API_KEY
        )
        name = factory.names(ix) + "2"
        vault = factory.create(
            old_controller.borrowed_token(),
            old_controller.collateral_token(),
            old_amm.A(),
            old_amm.fee(),
            old_controller.loan_discount(),
            old_controller.liquidation_discount(),
            old_amm.price_oracle_contract(),
            name,
            int(0.03e18 / 365 / 86400),
            int(0.3e18 / 365 / 86400) + rate_shift,
        )
        policy = policy_deployer.deploy(
            factory.address,
            WETH_AMM,
            old_controller.borrowed_token(),
            target_utilization,
            low_ratio,
            high_ratio,
            rate_shift,
        )
        gauge = factory.deploy_gauge(vault)

        print(name)
        print(f"Vault: {vault}")
        print(f"Gauge: {gauge}")
        print(f"Policy: {policy.address}")
        print()
