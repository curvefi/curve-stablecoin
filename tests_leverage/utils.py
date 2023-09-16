from ape import Contract, Project, accounts


def mint_tokens_for_testing(project: Project, account):
    """
    Provides given account with 100 WBTC and 1000 ETH, sfrxETH, wstETH
    Can be used only on local forked mainnet

    :return: None
    """

    # WBTC
    token_contract = Contract("0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599")
    token_owner = "0x9ff58f4fFB29fA2266Ab25e75e2A8b3503311656"
    project.provider.set_balance(token_owner, 10**18)
    amount = 100 * 10**8
    token_contract.transfer(account, amount, sender=accounts[token_owner])
    assert token_contract.balanceOf(account.address) >= amount

    # ETH
    # Set balance to twice amount + 1 - half will be wrapped + (potential) gas
    project.provider.set_balance(account.address, 1000 * 10**18)
    assert account.balance >= 1000 * 10**18

    # sfrxETH
    token_contract = Contract("0xac3e018457b222d93114458476f3e3416abbe38f")
    token_owner = "0xBA12222222228d8Ba445958a75a0704d566BF2C8"
    project.provider.set_balance(token_owner, 10**18)
    amount = 1000 * 10**18
    token_contract.transfer(account, amount, sender=accounts[token_owner])
    assert token_contract.balanceOf(account.address) >= amount

    # wstETH
    token_contract = Contract("0x7f39C581F595B53c5cb19bD0b3f8dA6c935E2Ca0")
    token_owner = "0x0B925eD163218f6662a35e0f0371Ac234f9E9371"
    project.provider.set_balance(token_owner, 10 ** 18)
    amount = 1000 * 10 ** 18
    token_contract.transfer(account, amount, sender=accounts[token_owner])
    assert token_contract.balanceOf(account.address) >= amount


CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
ROUTER = "0x99a58482bd75cbab83b27ec03ca68ff489b5788f"

frxETH = "0x5E8422345238F34275888049021821E8E08CAa1f"
stETH = "0xae7ab96520DE3A18E5e111B5EaAb095312D7fE84"

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

LLAMMAS = {
    "sfrxETH": "0x136e783846ef68c8bd00a3369f787df8d683a696",
    "wstETH": "0x37417b2238aa52d0dd2d6252d989e728e8f706e4",
    "WBTC": "0xe0438eb3703bf871e31ce639bd351109c88666ea",
    "WETH": "0x1681195c176239ac5e72d9aebacf5b2492e0c4ee",
    "sfrxETH2": "0xfa96ad0a9e64261db86950e2da362f5572c5c6fd",
    "tBTC": "0xf9bd9da2427a50908c4c6d1599d8e62837c2bcb0",
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
            "name": "crvUSD/USDC -> 3pool -> tricrypto2 -> frxeth",
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
            "name": "crvUSD/USDT -> tricrypto2 -> frxeth",
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
            "name": "crvUSD/USDP -> factory-v2-59 (USDP) -> tricrypto2 -> frxeth",
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
            "name": "crvUSD/TUSD -> tusd -> tricrypto2 -> frxeth",
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
            "name": "crvUSD/FRAX -> frax -> tricrypto2 -> frxeth",
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
            "name": "crvUSD/USDC -> 3pool -> tricrypto2 -> steth",
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
            "name": "crvUSD/USDT -> tricrypto2 -> steth",
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
            "name": "crvUSD/USDP -> factory-v2-59 (USDP) -> tricrypto2 -> steth",
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
            "name": "crvUSD/TUSD -> tusd -> tricrypto2 -> steth",
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
            "name": "crvUSD/FRAX -> frax -> tricrypto2 -> steth",
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
            "name": "crvUSD/USDC -> 3pool -> tricrypto2",
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
            "name": "crvUSD/USDT -> tricrypto2",
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
            "name": "crvUSD/USDP -> factory-v2-59 (USDP) -> tricrypto2",
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
            "name": "crvUSD/TUSD -> tusd -> tricrypto2",
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
            "name": "crvUSD/FRAX -> frax -> tricrypto2",
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
            "name": "crvUSD/USDC -> 3pool -> tricrypto2",
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
            "name": "crvUSD/USDT -> tricrypto2",
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
            "name": "crvUSD/USDP -> factory-v2-59 (USDP) -> tricrypto2",
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
            "name": "crvUSD/TUSD -> tusd -> tricrypto2",
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
            "name": "crvUSD/FRAX -> frax -> tricrypto2",
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
    },
    "sfrxETH2": {
        "usdc": {
            "name": "crvUSD/USDC -> 3pool -> tricrypto2 -> frxETH minter -> sfrxETH wrapper",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDC"],
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xbafa44efe7901e04e39dad13167d089c559c1138',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                COLLATERALS["sfrxETH"],
            ],
            "swap_params": [[1, 0, 1, 1, 2], [1, 2, 1, 1, 3], [0, 2, 1, 3, 3], [0, 0, 8, 0, 0], [0, 0, 8, 0, 0]],
            "factory_swap_addresses": [
                CRVUSD_POOLS["USDC"],
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "crvUSD/USDT -> tricrypto2 -> frxETH minter -> sfrxETH wrapper",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDT"],
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xbafa44efe7901e04e39dad13167d089c559c1138',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                COLLATERALS["sfrxETH"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 1, 2], [0, 2, 1, 3, 3], [0, 0, 8, 0, 0], [0, 0, 8, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                CRVUSD_POOLS["USDT"],
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdp": {
            "name": "crvUSD/USDP -> factory-v2-59 (USDP) -> tricrypto2 -> frxETH minter -> sfrxETH wrapper",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDP"],
                '0x8e870d67f660d95d5be530380d0ec0bd388289e1',
                '0xc270b3b858c335b6ba5d5b10e2da8a09976005ad',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xbafa44efe7901e04e39dad13167d089c559c1138',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                COLLATERALS["sfrxETH"],
            ],
            "swap_params": [[1, 0, 1, 1, 2], [0, 3, 2, 1, 4], [0, 2, 1, 3, 3], [0, 0, 8, 0, 0], [0, 0, 8, 0, 0]],
            "factory_swap_addresses": [
                CRVUSD_POOLS["USDP"],
                '0xc270b3b858c335b6ba5d5b10e2da8a09976005ad',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {
            "name": "crvUSD/TUSD -> tusd -> tricrypto2 -> frxETH minter -> sfrxETH wrapper",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["TUSD"],
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xbafa44efe7901e04e39dad13167d089c559c1138',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                COLLATERALS["sfrxETH"],
            ],
            "swap_params": [[1, 0, 1, 1, 2], [0, 3, 2, 1, 4], [0, 2, 1, 3, 3], [0, 0, 8, 0, 0], [0, 0, 8, 0, 0]],
            "factory_swap_addresses": [
                CRVUSD_POOLS["TUSD"],
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "frax": {
            "name": "crvUSD/FRAX -> frax -> tricrypto2 -> frxETH minter -> sfrxETH wrapper",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["FRAX"],
                '0x853d955acef822db058eb8505911ed77f175b99e',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
                '0xbafa44efe7901e04e39dad13167d089c559c1138',
                '0x5e8422345238f34275888049021821e8e08caa1f',
                '0xac3e018457b222d93114458476f3e3416abbe38f',
                COLLATERALS["sfrxETH"],
            ],
            "swap_params": [[1, 0, 1, 1, 2], [0, 3, 2, 1, 4], [0, 2, 1, 3, 3], [0, 0, 8, 0, 0], [0, 0, 8, 0, 0]],
            "factory_swap_addresses": [
                CRVUSD_POOLS["FRAX"],
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    },
    "tBTC": {
        "tbtc": {
            "name": "factory-tricrypto-2 (TricryptoLLAMA)",
            "route": [
                CRVUSD,
                '0x2889302a794da87fbf1d6db415c1492194663d13',
                COLLATERALS["tBTC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[0, 1, 1, 3, 3], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                '0x2889302a794da87fbf1d6db415c1492194663d13',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdc": {
            "name": "crvUSD/USDC -> 3pool -> tricrypto2 -> factory-crvusd-16 (tBTC/WBTC)",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDC"],
                '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WBTC"],
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                COLLATERALS["tBTC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 2], [1, 2, 1, 1, 3], [0, 1, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                CRVUSD_POOLS["USDC"],
                '0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "usdt": {
            "name": "crvUSD/USDT -> tricrypto2 -> factory-crvusd-16 (tBTC/WBTC)",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["USDT"],
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WBTC"],
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                COLLATERALS["tBTC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 1, 2], [0, 1, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                CRVUSD_POOLS["USDT"],
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "tusd": {
            "name": "crvUSD/TUSD -> tusd -> tricrypto2 -> factory-crvusd-16 (tBTC/WBTC)",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["TUSD"],
                '0x0000000000085d4780b73119b644ae5ecd22b376',
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WBTC"],
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                COLLATERALS["tBTC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 1, 2], [0, 3, 2, 1, 4], [0, 1, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                CRVUSD_POOLS["TUSD"],
                '0xecd5e75afb02efa118af914515d6521aabd189f1',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x0000000000000000000000000000000000000000',
            ],
        },
        "frax": {
            "name": "crvUSD/FRAX -> frax -> tricrypto2 -> factory-crvusd-16 (tBTC/WBTC)",
            "route": [
                CRVUSD,
                CRVUSD_POOLS["FRAX"],
                '0x853d955acef822db058eb8505911ed77f175b99e',
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0xdac17f958d2ee523a2206206994597c13d831ec7',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                COLLATERALS["WBTC"],
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                COLLATERALS["tBTC"],
                '0x0000000000000000000000000000000000000000',
                '0x0000000000000000000000000000000000000000',
            ],
            "swap_params": [[1, 0, 1, 1, 2], [0, 3, 2, 1, 4], [0, 1, 1, 3, 3], [0, 1, 1, 1, 2], [0, 0, 0, 0, 0]],
            "factory_swap_addresses": [
                CRVUSD_POOLS["FRAX"],
                '0xd632f22692fac7611d2aa1c0d552930d43caed3b',
                '0xd51a44d3fae010294c616388b506acda1bfaae46',
                '0xb7ecb2aa52aa64a717180e030241bc75cd946726',
                '0x0000000000000000000000000000000000000000',
            ],
        },
    },
}
