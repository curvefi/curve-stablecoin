from ape import project, accounts, networks
from ape.cli import NetworkBoundCommand, network_option
# account_option could be used when in prod?
import click


CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
ROUTER = "0xF0d4c12A5768D806021F80a262B4d39d26C58b8D"

COLLATERALS = {
    "sfrxETH": "0xac3E018457B222d93114458476f3E3416Abbe38F",
    "wstETH": "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
    "WBTC": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "sfrxETH2": "0xac3E018457B222d93114458476f3E3416Abbe38F",
    "tBTC": "0x18084fba666a33d37592fa2633fd49a74dd93a88",
}

CONTROLLERS = {
    "sfrxETH": "0x8472A9A7632b173c8Cf3a86D3afec50c35548e76",
    "wstETH": "0x100daa78fc509db39ef7d04de0c1abd299f4c6ce",
    "WBTC": "0x4e59541306910ad6dc1dac0ac9dfb29bd9f15c67",
    "WETH": "0xa920de414ea4ab66b97da1bfe9e6eca7d4219635",
    "sfrxETH2": "0xec0820efafc41d8943ee8de495fc9ba8495b15cf",
    "tBTC": "0x1c91da0223c763d2e0173243eadaa0a2ea47e704",
}

CRVUSD_POOLS = {
    "USDC": "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E",
    "USDT": "0x390f3595bCa2Df7d23783dFd126427CCeb997BF4",
    "USDP": "0xCa978A0528116DDA3cbA9ACD3e68bc6191CA53D0",
    "TUSD": "0x34D655069F4cAc1547E4C8cA284FfFF5ad4A8db0",
    "FRAX": "0x0cd6f267b2086bea681e922e19d40512511be538",
}

ROUTER_PARAMS_DELEVERAGE = {
    "sfrxETH": {
        "usdc": {
            "name": "sfrxETH wrapper -> frxeth -> factory-tricrypto-0 (TricryptoUSDC) -> crvUSD/USDC",
            "route": [
                COLLATERALS["sfrxETH"],
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                CRVUSD_POOLS["USDC"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                CRVUSD_POOLS["USDC"],
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "sfrxETH wrapper -> frxeth -> tricrypto2 -> crvUSD/USDT",
            "route": [
                COLLATERALS["sfrxETH"],
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                CRVUSD_POOLS["USDT"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                CRVUSD_POOLS["USDT"],
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tricrv": {
            "name": "sfrxETH wrapper -> frxeth -> factory-tricrypto-4 (TriCRV)",
            "route": [
                COLLATERALS["sfrxETH"],
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14',
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [1, 0, 1, 3, 3], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {
            "name": "sfrxETH wrapper -> frxeth -> tricrypto2 -> tusd -> crvUSD/TUSD",
            "route": [
                COLLATERALS["sfrxETH"],
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                CRVUSD_POOLS["TUSD"],
                CRVUSD,
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                CRVUSD_POOLS["TUSD"],
            ],
        },
        "frax": {
            "name": "sfrxETH wrapper -> frxeth -> tricrypto2 -> frax -> crvUSD/FRAX",
            "route": [
                COLLATERALS["sfrxETH"],
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0x853d955acef822db058eb8505911ed77f175b99e',
                CRVUSD_POOLS["FRAX"],
                CRVUSD,
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                CRVUSD_POOLS["FRAX"],
            ],
        },
    },
    "wstETH": {
        "usdc": {
            "name": "wstETH wrapper -> steth -> factory-tricrypto-0 (TricryptoUSDC) -> crvUSD/USDC",
            "route": [
                COLLATERALS["wstETH"],
                '0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0',
                '0xae7ab96520de3a18e5e111b5eaab095312d7fe84',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                CRVUSD_POOLS["USDC"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                CRVUSD_POOLS["USDC"],
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "wstETH wrapper -> steth -> tricrypto2 -> crvUSD/USDT",
            "route": [
                COLLATERALS["wstETH"],
                '0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0',
                '0xae7ab96520de3a18e5e111b5eaab095312d7fe84',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                CRVUSD_POOLS["USDT"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                CRVUSD_POOLS["USDT"],
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tricrv": {
            "name": "wstETH wrapper -> steth -> factory-tricrypto-4 (TriCRV)",
            "route": [
                COLLATERALS["wstETH"],
                '0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0',
                '0xae7ab96520de3a18e5e111b5eaab095312d7fe84',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14',
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [1, 0, 1, 3, 3], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                '0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {
            "name": "wstETH wrapper -> steth -> tricrypto2 -> tusd -> crvUSD/TUSD",
            "route": [
                COLLATERALS["wstETH"],
                '0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0',
                '0xae7ab96520de3a18e5e111b5eaab095312d7fe84',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                CRVUSD_POOLS["TUSD"],
                CRVUSD,
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                CRVUSD_POOLS["TUSD"],
            ],
        },
        "frax": {
            "name": "wstETH wrapper -> steth -> tricrypto2 -> frax -> crvUSD/FRAX",
            "route": [
                COLLATERALS["wstETH"],
                '0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0',
                '0xae7ab96520de3a18e5e111b5eaab095312d7fe84',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0x853d955acef822db058eb8505911ed77f175b99e',
                CRVUSD_POOLS["FRAX"],
                CRVUSD,
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                CRVUSD_POOLS["FRAX"],
            ],
        },
    },
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
            "swap_params": [[1, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                CRVUSD_POOLS["USDC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
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
        "tusd": {
            "name": "tricrypto2 -> tusd -> crvUSD/TUSD",
            "route": [
                COLLATERALS["WBTC"],
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                CRVUSD_POOLS["TUSD"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                CRVUSD_POOLS["TUSD"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdp": {
            "name": "tricrypto2 -> factory-v2-59 (USDP) -> crvUSD/USDP",
            "route": [
                COLLATERALS["WBTC"],
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xc270b3b858c335b6ba5d5b10e2da8a09976005ad',
                '0x8e870d67f660d95d5be530380d0ec0bd388289e1',
                CRVUSD_POOLS["USDP"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xc270b3b858c335b6ba5d5b10e2da8a09976005ad',
                CRVUSD_POOLS["USDP"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "frax": {
            "name": "tricrypto2 -> frax -> crvUSD/FRAX",
            "route": [
                COLLATERALS["WBTC"],
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0x853d955acef822db058eb8505911ed77f175b99e',
                CRVUSD_POOLS["FRAX"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                CRVUSD_POOLS["FRAX"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    },
    "WETH": {
        "usdc": {
            "name": "factory-tricrypto-0 (TricryptoUSDC) -> crvUSD/USDC",
            "route": [
                COLLATERALS["WETH"],
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
            "swap_params": [[2, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                CRVUSD_POOLS["USDC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "tricrypto2 -> crvUSD/USDT",
            "route": [
                COLLATERALS["WETH"],
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
            "swap_params": [[2, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                CRVUSD_POOLS["USDT"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tricrv": {
            "name": "factory-tricrypto-4 (TriCRV)",
            "route": [
                COLLATERALS["WETH"],
                '0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14',
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
            "swap_params": [[1, 0, 1, 3, 3], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {
            "name": "tricrypto2 -> tusd -> crvUSD/TUSD",
            "route": [
                COLLATERALS["WETH"],
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                CRVUSD_POOLS["TUSD"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[2, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                CRVUSD_POOLS["TUSD"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "frax": {
            "name": "tricrypto2 -> frax -> crvUSD/FRAX",
            "route": [
                COLLATERALS["WETH"],
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0x853d955acef822db058eb8505911ed77f175b99e',
                CRVUSD_POOLS["FRAX"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[2, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                CRVUSD_POOLS["FRAX"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    },
    "sfrxETH2": {
        "usdc": {
            "name": "sfrxETH wrapper -> frxeth -> factory-tricrypto-0 (TricryptoUSDC) -> crvUSD/USDC",
            "route": [
                COLLATERALS["sfrxETH"],
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                CRVUSD_POOLS["USDC"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                CRVUSD_POOLS["USDC"],
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "sfrxETH wrapper -> frxeth -> tricrypto2 -> crvUSD/USDT",
            "route": [
                COLLATERALS["sfrxETH"],
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                CRVUSD_POOLS["USDT"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                CRVUSD_POOLS["USDT"],
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tricrv": {
            "name": "sfrxETH wrapper -> frxeth -> factory-tricrypto-4 (TriCRV)",
            "route": [
                COLLATERALS["sfrxETH"],
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14',
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [1, 0, 1, 3, 3], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0x4ebdf703948ddcea3b11f675b4d1fba9d2414a14',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {
            "name": "sfrxETH wrapper -> frxeth -> tricrypto2 -> tusd -> crvUSD/TUSD",
            "route": [
                COLLATERALS["sfrxETH"],
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                CRVUSD_POOLS["TUSD"],
                CRVUSD,
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                CRVUSD_POOLS["TUSD"],
            ],
        },
        "frax": {
            "name": "sfrxETH wrapper -> frxeth -> tricrypto2 -> frax -> crvUSD/FRAX",
            "route": [
                COLLATERALS["sfrxETH"],
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0x853d955acef822db058eb8505911ed77f175b99e',
                CRVUSD_POOLS["FRAX"],
                CRVUSD,
            ],
            "swap_params": [[0, 0, 8, 0, 0], [1, 0, 1, 1, 2], [2, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                CRVUSD_POOLS["FRAX"],
            ],
        },
    },
    "tBTC": {
        "tbtc": {
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
            "swap_params": [[1, 0, 1, 3, 3], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
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
            "swap_params": [[1, 0, 1, 1, 2], [1, 0, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x7f86bf177dd4f3494b841a37e810a34dd56c829b',
                CRVUSD_POOLS["USDC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
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
        "tusd": {
            "name": "factory-crvusd-16 (tBTC/WBTC) -> tricrypto2 -> tusd -> crvUSD/TUSD",
            "route": [
                COLLATERALS["tBTC"],
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                CRVUSD_POOLS["TUSD"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 1, 2], [1, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                CRVUSD_POOLS["TUSD"],
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "frax": {
            "name": "factory-crvusd-16 (tBTC/WBTC) -> tricrypto2 -> frax -> crvUSD/FRAX",
            "route": [
                COLLATERALS["tBTC"],
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x2260fac5e5542a773aa44fbcfedf7c193bc2c599',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0x853d955acef822db058eb8505911ed77f175b99e',
                CRVUSD_POOLS["FRAX"],
                CRVUSD,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 1, 2], [1, 0, 1, 3, 3], [3, 0, 2, 1, 4], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                CRVUSD_POOLS["FRAX"],
                '0x0000000000000000000000000000000000000000',
            ],
        },
    }
}


@click.group()
def cli():
    """
    Script for test leverage
    """


@cli.command(
    cls=NetworkBoundCommand,
)
@network_option()
def deploy(network):
    kw = {}

    # Deployer address
    if ':local:' in network:
        account = accounts.test_accounts[0]
    elif ':mainnet:' in network:
        account = accounts.load('babe')
        account.set_autosign(True)
        max_base_fee = networks.active_provider.base_fee * 2
        kw = {
            'max_fee': max_base_fee,
            'max_priority_fee': min(int(0.5e9), max_base_fee)}
    else:
        account = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
        if account in accounts:
            account = accounts.load('babe')
            account.set_autosign(True)
        else:
            account = accounts.test_accounts[0]

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

        deleverage_contracts[collateral] = account.deploy(
            project.DeleverageZap,
            CONTROLLERS[collateral],
            COLLATERALS[collateral],
            ROUTER,
            routes,
            route_params,
            route_pools,
            route_names,
            **kw,
        )

    print('========================')
    print('sfrxETH:           ', deleverage_contracts["sfrxETH"].address)
    print('wstETH:            ', deleverage_contracts["wstETH"].address)
    print('WBTC:              ', deleverage_contracts["WBTC"].address)
    print('WETH:              ', deleverage_contracts["WETH"].address)
    print('sfrxETH2:          ', deleverage_contracts["sfrxETH2"].address)
    print('tBTC:              ', deleverage_contracts["tBTC"].address)

    import IPython
    IPython.embed()
