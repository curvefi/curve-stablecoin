#!/usr/bin/env python3

import boa
import json
import os
import sys
from time import sleep
import subprocess
from getpass import getpass
from eth_account import account
from boa.contracts.abi.abi_contract import ABIContractFactory

from networks import NETWORK, FRAXTAL


ADMIN = "0x4BbdFEd5696b3a8F6B3813506b5389959C5CDC57"  # Fraxtal Curve xgov
GAUGE_FACTORY = "0xeF672bD94913CB6f1d2812a6e18c1fFdEd8eFf5c"  # Fraxtal gauge factory has also the same address on L1
CRVUSD = "0xB102f7Efa0d5dE071A8D37B3548e1C7CB148Caf3"  # crvUSD-fraxtal
GAUGE_FUNDER = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
HARDHAT_COMMAND = ["npx", "hardhat", "node", "--fork", FRAXTAL, "--port", "8545"]

MARKET_PARAMS = [
    (
        "sfrxETH",
        {
            "collateral": "0xFC00000000000000000000000000000000000005",
            "A": 70,
            "fee": int(0.015e18),
            "borrowing_discount": int(0.07e18),
            "liquidation_discount": int(0.04e18),
            "min_borrow_rate": 2 * 10**16 // (365 * 86400),
            "max_borrow_rate": 30 * 10**16 // (365 * 86400),
            "oracle_contract": "0xF97c707024ef0DD3E77a0824555a46B622bfB500",
            "supply_limit": 2**256 - 1,
        },
    ),
    (
        "sFRAX",
        {
            "collateral": "0xfc00000000000000000000000000000000000008",
            "A": 285,
            "fee": int(0.015e18),
            "borrowing_discount": int(0.02e18),
            "liquidation_discount": int(0.015e18),
            "min_borrow_rate": 5 * 10**15 // (365 * 86400),
            "max_borrow_rate": 15 * 10**16 // (365 * 86400),
            "oracle_contract": "0x960ea3e3C7FB317332d990873d354E18d7645590",
            "supply_limit": 2**256 - 1,
        },
    ),
    (
        "FXS",
        {
            "collateral": "0xFc00000000000000000000000000000000000002",
            "A": 22,
            "fee": int(0.006e18),
            "borrowing_discount": int(0.155e18),
            "liquidation_discount": int(0.125e18),
            "min_borrow_rate": 2 * 10**16 // (365 * 86400),
            "max_borrow_rate": 30 * 10**16 // (365 * 86400),
            "oracle_contract": "0x8e0B8c8BB9db49a46697F3a5Bb8A308e744821D2",
            "supply_limit": 15 * 10**6 * 10**18,
        },
    ),
    (
        "CRV",
        {
            "collateral": "0x331B9182088e2A7d6D3Fe4742AbA1fB231aEcc56",
            "A": 22,
            "fee": int(0.006e18),
            "borrowing_discount": int(0.155e18),
            "liquidation_discount": int(0.125e18),
            "min_borrow_rate": 2 * 10**16 // (365 * 86400),
            "max_borrow_rate": 30 * 10**16 // (365 * 86400),
            "oracle_contract": "0x48A68C5511DfC355007b7B794890F26653A7bF93",
            "supply_limit": 15 * 10**6 * 10**18,
        },
    ),
]

CHAIN_ID = 252
GAUGE_FACTORY_ABI = [
    {
        "stateMutability": "nonpayable",
        "type": "function",
        "name": "deploy_gauge",
        "inputs": [
            {"name": "_lp_token", "type": "address"},
            {"name": "_salt", "type": "bytes32"},
            {"name": "_manager", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "address"}],
    },
]
GAUGE_FACTORY_ABI_ETH = [
    {
        "stateMutability": "payable",
        "type": "function",
        "name": "deploy_gauge",
        "inputs": [
            {"name": "_chain_id", "type": "uint256"},
            {"name": "_salt", "type": "bytes32"},
        ],
        "outputs": [{"name": "", "type": "address"}],
        "gas": 165352,
    }
]


def account_load(fname):
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == "__main__":
    if "--hardhat" in sys.argv[1:]:
        hardhat = subprocess.Popen(HARDHAT_COMMAND)
        sleep(5)

    if "--fork" in sys.argv[1:]:
        boa.env.fork(FRAXTAL)
        boa.env.eoa = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
    else:
        babe = account_load("babe")
        boa.set_network_env(FRAXTAL)
        boa.env.add_account(babe)
        boa.env._fork_try_prefetch_state = False

    amm_impl = boa.load_partial("contracts/AMM.vy").deploy_as_blueprint()
    controller_impl = boa.load_partial("contracts/Controller.vy").deploy_as_blueprint()
    vault_impl = boa.load("contracts/lending/Vault.vy")
    price_oracle_impl = boa.load_partial(
        "contracts/price_oracles/CryptoFromPool.vy"
    ).deploy_as_blueprint()  # XXX
    mpolicy_impl = boa.load_partial(
        "contracts/mpolicies/SemilogMonetaryPolicy.vy"
    ).deploy_as_blueprint()
    gauge_factory = ABIContractFactory.from_abi_dict(GAUGE_FACTORY_ABI).at(
        GAUGE_FACTORY
    )

    factory = boa.load(
        "contracts/lending/deprecated/OneWayLendingFactoryL2.vy",
        CRVUSD,
        amm_impl,
        controller_impl,
        vault_impl,
        price_oracle_impl,
        mpolicy_impl,
        GAUGE_FACTORY,
        ADMIN,
    )

    print("Deployed contracts:")
    print("==========================")
    print("AMM implementation:", amm_impl.address)
    print("Controller implementation:", controller_impl.address)
    print("Vault implementation:", vault_impl.address)
    print("Pool price oracle implementation:", price_oracle_impl.address)
    print("Monetary Policy implementation:", mpolicy_impl.address)
    print("Factory:", factory.address)
    print("==========================")

    if "--markets" in sys.argv[1:]:
        for name, p in MARKET_PARAMS:
            vault = factory.create(
                CRVUSD,
                p["collateral"],
                p["A"],
                p["fee"],
                p["borrowing_discount"],
                p["liquidation_discount"],
                p["oracle_contract"],
                name + "-long",
                p["min_borrow_rate"],
                p["max_borrow_rate"],
                p["supply_limit"],
            )
            salt = os.urandom(32)
            gauge_factory.deploy_gauge(vault, salt, GAUGE_FUNDER)
            print(f"Vault {name}: {vault}, salt: {salt.hex()}")
            p["salt"] = salt

        if "--fork" in sys.argv[1:]:
            boa.env.fork(NETWORK)
            boa.env.eoa = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
        else:
            boa.set_network_env(NETWORK)
            boa.env.add_account(babe)
            boa.env._fork_try_prefetch_state = False

        gauge_factory_eth = ABIContractFactory.from_abi_dict(GAUGE_FACTORY_ABI_ETH).at(
            GAUGE_FACTORY
        )

        for name, p in MARKET_PARAMS:
            if "--fork" not in sys.argv[1:]:
                sleep(
                    30
                )  # RPCs on Ethereum can change the node, so need to sleep to not fail
            salt = p["salt"]
            print(f"Deploying on Ethereum with salt: {salt.hex()}")
            gauge_factory_eth.deploy_gauge(CHAIN_ID, salt)

    if "--hardhat" in sys.argv[1:]:
        hardhat.wait()
