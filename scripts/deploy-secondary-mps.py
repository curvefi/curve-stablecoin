#!/usr/bin/env python3

"""
Deployed addresses (and example borrow rates):
WBTC 0x188041aD83145351Ef45F4bb91D08886648aEaF8 0.11111546984616
WETH 0x1A783886F03710ABf4a6833F50D5e69047123be6 0.113174760523104
TBTC 0x6Ddd163240c21189eD0c89D30f6681142bf05FFB 0.10298066829552
WSTETH 0x319C06103bc51b3c01a1A121451Aa5E2A2a7778f 0.153236318405616
"""

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from boa.network import NetworkEnv


NETWORK = "http://localhost:8545"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


FACTORY = "0xeA6876DDE9e3467564acBeE1Ed5bac88783205E0"
BORROWED_TOKEN = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"  # CRVUSD
U_0 = int(0.85e18)
LOW_RATIO = int(0.5e18)
HIGH_RATIO = int(3e18)
# WBTC, WETH, TBTC, WSTETH (== WETH)
NAMES = ["WBTC", "WETH", "TBTC", "WSTETH"]
# CRVUSD AMMS, not LlamaLend!!
AMMS = [
    "0xE0438Eb3703bF871E31Ce639bd351109c88666ea",
    "0x1681195C176239ac5E72d9aeBaCf5b2492E0C4ee",
    "0xf9bD9da2427a50908C4c6D1599D8e62837C2BCB0",
    "0x1681195C176239ac5E72d9aeBaCf5b2492E0C4ee",
]
SHIFTS = [0, 0, 0, int(4e16 / 365 / 86400)]

# LlamaLend controllers
CONTROLLERS = [
    "0xcaD85b7fe52B1939DCEebEe9bCf0b2a5Aa0cE617",
    "0xaade9230AA9161880E13a38C83400d3D1995267b",
    "0x413FD2511BAD510947a91f5c6c79EBD8138C29Fc",
    "0x1E0165DbD2019441aB7927C018701f3138114D71",
]


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
        boa.set_env(NetworkEnv(NETWORK))
        boa.env.add_account(account_load("babe"))
        boa.env._fork_try_prefetch_state = False

    policies = [
        boa.load(
            "contracts/mpolicies/SecondaryMonetaryPolicy.vy",
            FACTORY,
            amm,
            BORROWED_TOKEN,
            U_0,
            LOW_RATIO,
            HIGH_RATIO,
            shift,
        )
        for (amm, shift) in zip(AMMS, SHIFTS)
    ]

    for n, p, c in zip(NAMES, policies, CONTROLLERS):
        print(n, p.address, p.rate(c) * 86400 * 365 / 1e18)
