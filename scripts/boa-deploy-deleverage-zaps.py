#!/usr/bin/env python3

import boa
import json
import os
from getpass import getpass
from eth_account import account
from networks import ETHEREUM


def account_load(fname):
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
ROUTER = "0x45312ea0eFf7E09C83CBE249fa1d7598c4C8cd4e"

COLLATERALS = {
    "WBTC": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
    "tBTC": "0x18084fba666a33d37592fa2633fd49a74dd93a88",
}

CONTROLLERS = {
    "WBTC": "0x4e59541306910ad6dc1dac0ac9dfb29bd9f15c67",
    "tBTC": "0x1c91da0223c763d2e0173243eadaa0a2ea47e704",
}

CRVUSD_POOLS = {
    "USDC": "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E",
    "USDT": "0x390f3595bCa2Df7d23783dFd126427CCeb997BF4",
}

ROUTER_PARAMS_DELEVERAGE = {
    "WBTC": {
        "usdc": {
            "name": "factory-tricrypto-0 (TricryptoUSDC) -> crvUSD/USDC",
            "route": [
                COLLATERALS["WBTC"],
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                CRVUSD_POOLS["USDC"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 30, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                CRVUSD_POOLS["USDC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "factory-tricrypto-1 (TricryptoUSDT) -> crvUSD/USDT",
            "route": [
                COLLATERALS["WBTC"],
                '0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                CRVUSD_POOLS["USDT"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 30, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4',
                CRVUSD_POOLS["USDT"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdc2": {
            "name": "tricrypto2 -> 3pool -> crvUSD/USDC",
            "route": [
                COLLATERALS["WBTC"],
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                CRVUSD_POOLS["USDC"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 3, 3], [2, 1, 1, 1, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                CRVUSD_POOLS["USDC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt2": {
            "name": "tricrypto2 -> crvUSD/USDT",
            "route": [
                COLLATERALS["WBTC"],
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                CRVUSD_POOLS["USDT"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                CRVUSD_POOLS["USDT"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "yb": {
            "name": "crvUSD/WBTC (YB)",
            "route": [
                COLLATERALS["WBTC"],
                "0xD9FF8396554A0d18B2CFbeC53e1979b7ecCe8373",
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 20, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xD9FF8396554A0d18B2CFbeC53e1979b7ecCe8373',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    },
    "tBTC": {
        "crvusd": {
            "name": "factory-tricrypto-2 (TricryptoLLAMA)",
            "route": [
                COLLATERALS["tBTC"],
                '0x2889302a794da87fbf1d6db415c1492194663d13',
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 30, 3], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x2889302a794da87fbf1d6db415c1492194663d13',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdc": {
            "name": "factory-crvusd-16 (tBTC/WBTC) -> factory-tricrypto-0 (TricryptoUSDC) -> crvUSD/USDC",
            "route": [
                COLLATERALS["tBTC"],
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599',
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                CRVUSD_POOLS["USDC"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 1, 2], [1, 0, 1, 30, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                CRVUSD_POOLS["USDC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "factory-crvusd-16 (tBTC/WBTC) -> factory-tricrypto-1 (TricryptoUSDT) -> crvUSD/USDT",
            "route": [
                COLLATERALS["tBTC"],
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599',
                '0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                CRVUSD_POOLS["USDT"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 1, 2], [1, 0, 1, 30, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4',
                CRVUSD_POOLS["USDT"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt2": {
            "name": "factory-crvusd-16 (tBTC/WBTC) -> tricrypto2 -> crvUSD/USDT",
            "route": [
                COLLATERALS["tBTC"],
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                CRVUSD_POOLS["USDT"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 1, 2], [1, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                CRVUSD_POOLS["USDT"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "yb": {
            "name": "crvUSD/tBTC (YB)",
            "route": [
                COLLATERALS["tBTC"],
                "0xf1F435B05D255a5dBdE37333C0f61DA6F69c6127",
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 20, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xf1F435B05D255a5dBdE37333C0f61DA6F69c6127',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    }
}


if __name__ == '__main__':
    boa.set_network_env(ETHEREUM)
    boa.env.add_account(account_load('curve-deployer'))
    boa.env._fork_try_prefetch_state = False

    deleverage_contracts = {}
    for collateral in COLLATERALS.keys():
        routes = []
        route_params = []
        route_pools = []
        route_names = []
        for route in ROUTER_PARAMS_DELEVERAGE[collateral].values():
            routes.append(route["route"])
            route_params.append(route["swap_params"])
            route_pools.append(route["factory_swap_addresses"])
            route_names.append(route["name"])

        deleverage_contracts[collateral] = boa.load('contracts/zaps/deprecated/DeleverageZap.vy',
            CONTROLLERS[collateral],
            COLLATERALS[collateral],
            ROUTER,
            routes,
            route_params,
            route_pools,
            route_names,
        )

    print('========================')
    print('WBTC:              ', deleverage_contracts["WBTC"].address)
    print('tBTC:              ', deleverage_contracts["tBTC"].address)

    import IPython
    IPython.embed()
