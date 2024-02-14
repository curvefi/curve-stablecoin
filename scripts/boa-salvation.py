#!/usr/bin/env python3

import boa
import json
import os
import sys
from getpass import getpass
from eth_account import account
from boa.network import NetworkEnv


RANSOM = 15 * 10 ** 6 * 10 ** 18
IDX = 3  # TUSD

NETWORK = f"https://eth-mainnet.alchemyapi.io/v2/{os.environ['WEB3_ETHEREUM_MAINNET_ALCHEMY_API_KEY']}"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

POOLS = [
    "0x4dece678ceceb27446b35c672dc7d61f30bad69e",  # USDC/crvUSD
    "0x390f3595bca2df7d23783dfd126427cceb997bf4",  # USDT/crvUSD
    "0xca978a0528116dda3cba9acd3e68bc6191ca53d0",  # USDP/crvUSD
    "0x34d655069f4cac1547e4c8ca284ffff5ad4a8db0",  # TUSD/crvUSD
]
PEG_KEEPERS = [
    "0xaA346781dDD7009caa644A4980f044C50cD2ae22",  # USDC
    "0xE7cd2b4EB1d98CD6a4A48B6071D46401Ac7DC5C8",  # USDT
    "0x6B765d07cf966c745B340AdCa67749fE75B5c345",  # USDP
    "0x1ef89Ed0eDd93D1EC09E4c07373f69C49f4dcCae",  # TUSD
]
CRVUSD = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"
SALVATION = ZERO_ADDRESS

ETHERSCAN_API = os.environ["ETHERSCAN_TOKEN"]
_contracts = {}


def _pool(idx):
    if POOLS[idx] not in _contracts:
        # _contracts[POOLS[idx]] = boa.load_partial("contracts/StableSwap.vy").at(POOLS[idx])
        _contracts[POOLS[idx]] = boa.from_etherscan(POOLS[idx], name="StableSwap", api_key=ETHERSCAN_API)
    return _contracts[POOLS[idx]]


def _peg_keeper(idx):
    if PEG_KEEPERS[idx] not in _contracts:
        # _contracts[PEG_KEEPERS[idx]] = boa.load_partial("contracts/stabilizer/PegKeeper.vy").at(PEG_KEEPERS[idx])
        _contracts[PEG_KEEPERS[idx]] = boa.from_etherscan(PEG_KEEPERS[idx], name="PegKeeper", api_key=ETHERSCAN_API)
    return _contracts[PEG_KEEPERS[idx]]


def _coins(pool):
    coins = [pool]
    for coin in [pool.coins(0), CRVUSD]:
        if coin not in _contracts:
            _contracts[coin] = boa.from_etherscan(pool.coins(0), name="coin", api_key=ETHERSCAN_API)
        coins.append(_contracts[coin])
    return coins


def deploy():
    salvation = boa.load_partial("contracts/stabilizer/Salvation.vy")
    if SALVATION != ZERO_ADDRESS:
        return salvation.at(SALVATION)
    return salvation.deploy()


def buy_out(idx=IDX, ransom=RANSOM, max_total_supply=None, max_price=None, salvation=None):
    pool, pk = _pool(idx), _peg_keeper(idx)
    if not max_total_supply:
        max_total_supply = pool.totalSupply() * 101 // 100
    if not max_price:
        max_price = pool.price_oracle() * 101 // 100
    if not salvation:
        salvation = deploy()

    coins = _coins(pool)
    initial_balances = [
        coin.balanceOf(boa.env.eoa) for coin in coins
    ]

    bought_out = salvation.buy_out(pool, pk, ransom, max_total_supply, max_price)
    print(f"Bought out: {bought_out / 10 ** 18:>11.2f} crvUSD")
    print(f"Remaining:  {pk.debt() / 10 ** 18:>11.2f} crvUSD")

    diffs = []
    for coin, initial_balance in zip(coins, initial_balances):
        delimiter = 10 ** coin.decimals()
        new_balance = coin.balanceOf(boa.env.eoa)
        diff = new_balance - initial_balance
        print(f"{coin.symbol()}: {initial_balance / delimiter:.2f} -> {new_balance / delimiter:.2f} "
              f"({'+' if diff > 0 else ''}{diff / delimiter:.2f})")
        diffs.append(diff)
    print(f"Total: {diffs[1] / pool.price_oracle() + diffs[2] / 10 ** 18:.2f} crvUSD")


def simulate(idx=IDX, ransom=RANSOM):
    print("Simulation")
    salvation = deploy()
    to = boa.env.eoa
    if CRVUSD not in _contracts:
        _contracts[CRVUSD] = boa.from_etherscan(CRVUSD, name="crvUSD", api_key=ETHERSCAN_API)
    crvusd = _contracts[CRVUSD]

    for i in range(5):
        if _peg_keeper(idx).debt() < 10 ** 18:
            print("Peg Keeper is free")
            break

        print(f"Iteration {i}")
        with boa.env.prank("0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC"):
            balance = crvusd.balanceOf(to)
            if balance < ransom:
                crvusd.mint(to, ransom - balance)

        crvusd.approve(salvation, ransom)

        buy_out(idx, ransom, salvation=salvation)
        boa.env.time_travel(seconds=15 * 60)  # PegKeeper:ACTION_DELAY
        print()


def account_load(fname):
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == '__main__':
    if '--fork' in sys.argv[1:]:
        boa.env.fork(NETWORK)

        boa.env.eoa = '0xbabe61887f1de2713c6f97e567623453d3C79f67'
        simulate()
    else:
        boa.set_env(NetworkEnv(NETWORK))
        boa.env.add_account(account_load('babe'))
        boa.env._fork_try_prefetch_state = False
        buy_out()
