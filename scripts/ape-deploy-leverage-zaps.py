from time import sleep
from ape import project, accounts, Contract, networks
from ape.cli import NetworkBoundCommand, network_option
from ape import chain
# account_option could be used when in prod?
import click


CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
ROUTER = "0x99a58482bd75cbab83b27ec03ca68ff489b5788f"

frxETH = "0x5E8422345238F34275888049021821E8E08CAa1f"
stETH = "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"

COLLATERALS = {
    "sfrxETH": "0xac3E018457B222d93114458476f3E3416Abbe38F",
    "wstETH": "0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0",
    "WBTC": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
    "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
}

CONTROLLERS = {
    "sfrxETH": "0x8472A9A7632b173c8Cf3a86D3afec50c35548e76",
    "wstETH": "0x100daa78fc509db39ef7d04de0c1abd299f4c6ce",
    "WBTC": "0x4e59541306910ad6dc1dac0ac9dfb29bd9f15c67",
    "WETH": "0xa920de414ea4ab66b97da1bfe9e6eca7d4219635",
}

CRVUSD_POOLS = {
    "USDC": "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E",
    "USDT": "0x390f3595bCa2Df7d23783dFd126427CCeb997BF4",
    "USDP": "0xCa978A0528116DDA3cbA9ACD3e68bc6191CA53D0",
    "TUSD": "0x34D655069F4cAc1547E4C8cA284FfFF5ad4A8db0",
    "FRAX": "0x0cd6f267b2086bea681e922e19d40512511be538",
}

ROUTER_PARAMS = {
    "sfrxETH": {
        "usdc": {
            "name": "crvUSD/USDC --> 3pool --> tricrypto2 --> frxeth",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDC"],
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                frxETH,
            ],
            "swap_params": [[1, 0, 1], [1, 2, 1], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "crvUSD/USDT --> tricrypto2 --> frxeth",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDT"],
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                frxETH,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 2, 3], [0, 1, 1], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdp": {
            "name": "crvUSD/USDP --> factory-v2-59 (USDP) -> tricrypto2 --> frxeth",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDP"],
                '0x8e870d67f660d95d5be530380d0ec0bd388289e1',
                '0xc270b3b858c335b6ba5d5b10e2da8a09976005ad',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                frxETH,
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {
            "name": "crvUSD/TUSD --> tusd -> tricrypto2 --> frxeth",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["TUSD"],
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                frxETH,
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "frax": {
            "name": "crvUSD/FRAX --> frax -> tricrypto2 --> frxeth",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["FRAX"],
                '0x853d955acef822db058eb8505911ed77f175b99e',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xa1f8a6807c402e4a15ef4eba36528a3fed24e577',
                frxETH,
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    },
    "wstETH": {
        "usdc": {
            "name": "crvUSD/USDC --> 3pool --> tricrypto2 --> steth",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDC"],
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                stETH,
            ],
            "swap_params": [[1, 0, 1], [1, 2, 1], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "crvUSD/USDT --> tricrypto2 --> steth",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDT"],
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                stETH,
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 2, 3], [0, 1, 1], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdp": {
            "name": "crvUSD/USDP --> factory-v2-59 (USDP) -> tricrypto2 --> steth",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDP"],
                '0x8e870d67f660d95d5be530380d0ec0bd388289e1',
                '0xc270b3b858c335b6ba5d5b10e2da8a09976005ad',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                stETH,
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {
            "name": "crvUSD/TUSD --> tusd -> tricrypto2 --> steth",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["TUSD"],
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                stETH,
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "frax": {
            "name": "crvUSD/FRAX --> frax -> tricrypto2 --> steth",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["FRAX"],
                '0x853d955acef822db058eb8505911ed77f175b99e',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xdc24316b9ae028f1497c275eb9192a3ea0f67022',
                stETH,
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 1, 1]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    },
    "WBTC": {
        "usdc": {
            "name": "crvUSD/USDC --> 3pool --> tricrypto2",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDC"],
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WBTC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [1, 2, 1], [0, 1, 3], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "crvUSD/USDT --> tricrypto2",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDT"],
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WBTC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 1, 3], [0, 0, 0], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdp": {
            "name": "crvUSD/USDP --> factory-v2-59 (USDP) -> tricrypto2",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDP"],
                '0x8e870d67f660d95d5be530380d0ec0bd388289e1',
                '0xc270b3b858c335b6ba5d5b10e2da8a09976005ad',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WBTC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 1, 3], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {
            "name": "crvUSD/TUSD --> tusd -> tricrypto2",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["TUSD"],
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WBTC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 1, 3], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "frax": {
            "name": "crvUSD/FRAX --> frax -> tricrypto2",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["FRAX"],
                '0x853d955acef822db058eb8505911ed77f175b99e',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WBTC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 1, 3], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    },
    "WETH": {
        "usdc": {
            "name": "crvUSD/USDC --> 3pool --> tricrypto2",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDC"],
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WETH"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [1, 2, 1], [0, 2, 3], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "crvUSD/USDT --> tricrypto2",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDT"],
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WETH"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 2, 3], [0, 0, 0], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdp": {
            "name": "crvUSD/USDP --> factory-v2-59 (USDP) -> tricrypto2",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDP"],
                '0x8e870d67f660d95d5be530380d0ec0bd388289e1',
                '0xc270b3b858c335b6ba5d5b10e2da8a09976005ad',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WETH"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {
            "name": "crvUSD/TUSD --> tusd -> tricrypto2",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["TUSD"],
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WETH"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "frax": {
            "name": "crvUSD/FRAX --> frax -> tricrypto2",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["FRAX"],
                '0x853d955acef822db058eb8505911ed77f175b99e',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WETH"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1], [0, 3, 2], [0, 2, 3], [0, 0, 0]],
            "factory_swap_addresses": [
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
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

    leverage_contracts = {}
    for collateral in COLLATERALS.keys():
        routes = []
        route_params = []
        route_pools = []
        route_names = []
        for route in ROUTER_PARAMS[collateral].values():
            routes.append(route["route"])
            route_params.append(route["swap_params"])
            route_pools.append(route["factory_swap_addresses"])
            route_names.append(route["name"])

        contract = project.LeverageZap
        if collateral == "sfrxETH":
            contract = project.LeverageZapSfrxETH
        if collateral == "wstETH":
            contract = project.LeverageZapWstETH
        leverage_contracts[collateral] = account.deploy(
            contract,
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
    print('sfrxETH:           ', leverage_contracts["sfrxETH"].address)
    print('wstETH:            ', leverage_contracts["wstETH"].address)
    print('WBTC:              ', leverage_contracts["WBTC"].address)
    print('WETH:              ', leverage_contracts["WETH"].address)


    import IPython
    IPython.embed()
