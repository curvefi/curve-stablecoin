#!/usr/bin/env python3

import boa
import json
import os
import sys
from time import sleep
from getpass import getpass
from eth_account import account
from boa.contracts.abi.abi_contract import ABIContractFactory
from vyper.compiler.settings import Settings as CompilerSettings
from vyper.compiler.settings import OptimizationLevel

from networks import NETWORK, SONIC


ADMIN = "0x6c9578402A3ace046A12839f45F84Aa5448E9c30"  # Sonic Curve xgov
GAUGE_FACTORY = "0xf3A431008396df8A8b2DF492C913706BDB0874ef"
GAUGE_FACTORY_ETH = "0x306A45a1478A000dC701A6e1f7a569afb8D9DCD6"
CRVUSD = "0x7FFf4C4a827C84E32c5E175052834111B2ccd270"  # crvUSD-sonic
GAUGE_FUNDER = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
HARDHAT_COMMAND = ["npx", "hardhat", "node", "--fork", SONIC, "--port", "8545"]

# S, wETH, stS, oS

MARKET_PARAMS = [
    (
        "wS",
        {
            "collateral": "0x039e2fb66102314ce7b64ce5ce3e5183bc94ad38",
            "A": 17,
            "fee": int(0.005e18),
            "borrowing_discount": int(0.17e18),
            "liquidation_discount": int(0.14e18),
            "min_borrow_rate": 1 * 10**16 // (365 * 86400),
            "max_borrow_rate": 60 * 10**16 // (365 * 86400),
            "oracle_contract": "0x1daB6560494B04473A0BE3E7D83CF3Fdf3a51828",
            "supply_limit": 2**256 - 1,
        },
    ),
    (
        "stS",
        {
            "collateral": "0xE5DA20F15420aD15DE0fa650600aFc998bbE3955",
            "A": 17,
            "fee": int(0.005e18),
            "borrowing_discount": int(0.17e18),
            "liquidation_discount": int(0.14e18),
            "min_borrow_rate": 1 * 10**16 // (365 * 86400),
            "max_borrow_rate": 60 * 10**16 // (365 * 86400),
            "oracle_contract": "0x58e57cA18B7A47112b877E31929798Cd3D703b0f",
            "supply_limit": 2**256 - 1,
        },
    ),
    (
        "wOS",
        {
            "collateral": "0x9F0dF7799f6FDAd409300080cfF680f5A23df4b1",
            "A": 17,
            "fee": int(0.005e18),
            "borrowing_discount": int(0.17e18),
            "liquidation_discount": int(0.14e18),
            "min_borrow_rate": 1 * 10**16 // (365 * 86400),
            "max_borrow_rate": 60 * 10**16 // (365 * 86400),
            "oracle_contract": "0x3a1659Ddcf2339Be3aeA159cA010979FB49155FF",
            "supply_limit": 2**256 - 1,
        },
    ),
    (
        "scETH",
        {
            "collateral": "0x3bcE5CB273F0F148010BbEa2470e7b5df84C7812",
            "A": 70,
            "fee": int(0.005e18),
            "borrowing_discount": int(0.07e18),
            "liquidation_discount": int(0.04e18),
            "min_borrow_rate": 2 * 10**16 // (365 * 86400),
            "max_borrow_rate": 40 * 10**16 // (365 * 86400),
            "oracle_contract": "0x2F0AF8eC2f5893392843a0F647A30A141dba9DaF",
            # 'oracle_contract': '0xB755B949C126C04e0348DD881a5cF55d424742B2', wETH
            "supply_limit": 2**256 - 1,
        },
    ),
    (
        "scUSD",
        {
            "collateral": "0xd3DCe716f3eF535C5Ff8d041c1A41C3bd89b97aE",  # Params same as USDe
            "A": 500,
            "fee": int(0.001e18),
            "borrowing_discount": int(0.015e18),
            "liquidation_discount": int(0.01e18),
            "min_borrow_rate": 1 * 10**16 // (365 * 86400),
            "max_borrow_rate": 35 * 10**16 // (365 * 86400),
            "oracle_contract": "0x48A68C5511DfC355007b7B794890F26653A7bF93",  # Usually 1.0
            "supply_limit": 2**256 - 1,
        },
    ),
]

CHAIN_ID = 146
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
SONIC_ARGS = {
    "settings": CompilerSettings(
        evm_version="shanghai", optimize=OptimizationLevel.CODESIZE
    )
}


def account_load(fname):
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


if __name__ == "__main__":
    if "--fork" in sys.argv[1:]:
        boa.env.fork(SONIC)
        boa.env.eoa = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
    else:
        babe = account_load("babe")
        boa.set_network_env(SONIC)
        boa.env.add_account(babe)
        boa.env._fork_try_prefetch_state = False

    amm_impl = boa.load_partial(
        "curve_stablecoin/AMM.vy", compiler_args=SONIC_ARGS
    ).deploy_as_blueprint()
    controller_impl = boa.load_partial(
        "curve_stablecoin/Controller.vy", compiler_args=SONIC_ARGS
    ).deploy_as_blueprint()
    vault_impl = boa.load_partial(
        "curve_stablecoin/lending/Vault.vy", compiler_args=SONIC_ARGS
    ).deploy()
    price_oracle_impl = boa.load_partial(
        "curve_stablecoin/price_oracles/CryptoFromPool.vy", compiler_args=SONIC_ARGS
    ).deploy_as_blueprint()
    mpolicy_impl = boa.load_partial(
        "curve_stablecoin/mpolicies/SemilogMonetaryPolicy.vy", compiler_args=SONIC_ARGS
    ).deploy_as_blueprint()
    gauge_factory = ABIContractFactory.from_abi_dict(GAUGE_FACTORY_ABI).at(
        GAUGE_FACTORY
    )

    factory = boa.load_partial(
        "curve_stablecoin/lending/deprecated/OneWayLendingFactoryL2.vy",
        compiler_args=SONIC_ARGS,
    ).deploy(
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
    sleep(5)

    if "--markets" in sys.argv[1:]:
        for idx, (name, p) in enumerate(MARKET_PARAMS):
            factory.create(
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
                gas=15_000_000,
            )
            sleep(5)
            vault = factory.vaults(idx)
            salt = os.urandom(32)
            try:
                gauge_factory.deploy_gauge(vault, salt, GAUGE_FUNDER, gas=1_000_000)
            except Exception as e:
                print(f"Error {e} is not error?")
            print(f"Vault {name}: {vault}, salt: {salt.hex()}")
            p["salt"] = salt
            sleep(5)

        if "--fork" in sys.argv[1:]:
            boa.env.fork(NETWORK)
            boa.env.eoa = "0xbabe61887f1de2713c6f97e567623453d3C79f67"
        else:
            boa.set_network_env(NETWORK)
            boa.env.add_account(babe)
            boa.env._fork_try_prefetch_state = False

        gauge_factory_eth = ABIContractFactory.from_abi_dict(GAUGE_FACTORY_ABI_ETH).at(
            GAUGE_FACTORY_ETH
        )

        for name, p in MARKET_PARAMS:
            salt = p["salt"]
            print(f"Deploying on Ethereum {name} with salt: {salt.hex()}")
            try:
                gauge_factory_eth.deploy_gauge(CHAIN_ID, salt)
            except Exception as e:
                print(
                    f"Maybe {e} is also success? All RPCs are complete shit, get Vitalik on the line"
                )
            if "--fork" not in sys.argv[1:]:
                sleep(
                    250
                )  # RPCs on Ethereum can change the node, so need to sleep to not fail
