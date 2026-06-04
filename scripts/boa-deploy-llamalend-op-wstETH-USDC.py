#!/usr/bin/env python3

import argparse
import json
import os
import time
from getpass import getpass
from pathlib import Path

import boa
import boa_solidity
import requests
import solcx
from boa.network import NetworkEnv
from boa.rpc import EthereumRPC
from eth_account import Account


# Token addresses for Optimism
WSTETH = "0x1F32b1c2345538c0c6f582fCB022739c4A194Ebb"
USDC = "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85"
CHAINLINK_FEED = "0x698B585CbC4407e2D54aa898B2600B53C68958f7" # wstETH / USD

# Market parameters (using wstETH/USDC parameters from doc as requested)
A = 83
FEE = int(0.014 * 10**18) # 1.4%
LOAN_DISCOUNT = int(0.14 * 10**18) # 14%
LIQUIDATION_DISCOUNT = int(0.11 * 10**18) # 11%
MIN_RATE = 158548959 # 0.5% APR
MAX_RATE = 15854895991 # 50% APR
SUPPLY_LIMIT = 2**256 - 1

borrow_cap = 2660000
admin_percentage = 10

OBSERVATIONS = 20
INTERVAL = 30
CHAIN_ID = 10


def _load_account(keystore_path: str) -> Account:
    """Decrypt a keystore file."""
    path = Path(keystore_path)
    with open(path) as f:
        pkey = Account.decrypt(json.load(f), getpass(f"Password for {path.name}: "))
    return Account.from_key(pkey)


class RetryRPC(EthereumRPC):
    def fetch(self, method, params):
        delay = 1.0
        for attempt in range(6):
            try:
                return super().fetch(method, params)
            except requests.exceptions.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status != 503 or attempt == 5:
                    raise
                time.sleep(delay)
                delay *= 1.5


def _deploy(deployer: str, dry_run: bool, report_path: Path, factory_deployment: Path) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    existing = json.loads(factory_deployment.read_text())
    factory = boa.load_partial("curve_stablecoin/lending/LendFactory.vy").at(
        existing["factory"]
    )
    configurator = boa.load_partial("curve_stablecoin/Configurator.vy").at(existing["configurator"])

    monetary_policy = boa.load_partial(
        "curve_stablecoin/mpolicies/SemilogMonetaryPolicy.vy"
    ).deploy(USDC, MIN_RATE, MAX_RATE, factory.address)

    solcx.install_solc("0.8.25")
    solcx.set_solc_version("0.8.25")
    oracle = boa.load_partial_solc("scripts/solidity/ChainlinkEMA.sol").deploy(
        CHAINLINK_FEED,
        OBSERVATIONS,
        INTERVAL,
    )

    deployed = factory.create(
        USDC,
        WSTETH,
        A,
        FEE,
        LOAN_DISCOUNT,
        LIQUIDATION_DISCOUNT,
        oracle.address,
        monetary_policy.address,
        SUPPLY_LIMIT,
        sender=deployer,
    )

    chain_id = CHAIN_ID
    if hasattr(boa.env, "get_chain_id"):
        chain_id = boa.env.get_chain_id()

    # this only works if the factory is owned by the address doing the tx here
    # if the DAO owns the factory, a DAO vote is needed
    # set borrow cap and admin fee only if deployer is admin

    if factory.admin() == deployer:
        # set borrow cap to 2.66 Mil USDC (6 decimals)
        controller = boa.load_partial("curve_stablecoin/lending/LendController.vy").at(deployed[1])
        configurator.set_borrow_cap(controller, borrow_cap * 10**6, sender=deployer)
        # set admin fee to 10%
        configurator.set_admin_percentage(controller, admin_percentage * 10**18, sender=deployer)
    else:
        borrow_cap = 0
        admin_percentage = 0
        print(f"[SKIP] deployer {deployer} is not factory admin — skipping borrow cap and admin fee setup")

    report = {
        "chain_id": chain_id,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "factory": factory.address,
        "monetary_policy": monetary_policy.address,
        "price_oracle": oracle.address,
        "vault": deployed[0],
        "controller": deployed[1],
        "amm": deployed[2],
        "params": {
            "borrowed_token": USDC,
            "collateral_token": WSTETH,
            "chainlink_feed": CHAINLINK_FEED,
            "A": A,
            "fee": FEE,
            "loan_discount": LOAN_DISCOUNT,
            "liquidation_discount": LIQUIDATION_DISCOUNT,
            "min_rate": MIN_RATE,
            "max_rate": MAX_RATE,
            "supply_limit": SUPPLY_LIMIT,
            "observations": OBSERVATIONS,
            "interval": INTERVAL,
            "borrow_cap": borrow_cap * 10**6,
			"admin_percentage": admin_percentage * 10**18
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("Factory:", factory.address)
    print("Monetary Policy:", monetary_policy.address)
    print("Price Oracle:", oracle.address)
    print("Vault:", deployed[0])
    print("Controller:", deployed[1])
    print("AMM:", deployed[2])
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy LlamaLend wstETH/USDC on OP")
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keystore",
        default=os.environ.get("DEPLOYER_KEYSTORE"),
        help="Path to keystore JSON file",
    )
    parser.add_argument(
        "--factory-deployment",
        default="deployments/llamalend-op-testing.jsonc",
        help="Path to existing factory deployment JSON to read factory address from",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend-op-wstETH-USDC.jsonc",
        help="Where to write the deployment report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")

    report_path = Path(args.report_path)
    factory_deployment = Path(args.factory_deployment)

    if not factory_deployment.exists():
        raise SystemExit(f"Factory deployment not found: {factory_deployment}")

    if args.dry_run:
        if not args.keystore:
            raise SystemExit("Missing --keystore or DEPLOYER_KEYSTORE for dry-run address")
        deployer = _load_account(args.keystore).address
        with boa.fork(args.rpc_url):
            _deploy(deployer, dry_run=True, report_path=report_path, factory_deployment=factory_deployment)
    else:
        if not args.keystore:
            raise SystemExit("Missing --keystore or DEPLOYER_KEYSTORE")
        acct = _load_account(args.keystore)
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _deploy(acct.address, dry_run=False, report_path=report_path, factory_deployment=factory_deployment)


if __name__ == "__main__":
    main()
