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


LLV2ETH = "0x79CC1c5C0171FF25eF391055e529A56A12Bf3D39"
LLV2USD = "0xE8e9Cd957DC2b5A32ea822a3799f65940cF51f19"

CHAINLINK_FEED = "0x13e3Ee699D1909E989722E753853AE30b17e08c5" # ETH / USD = ETH in USD (WSTETH in ETH)


A = 70
FEE = 6 * 10**15
LOAN_DISCOUNT = 70000000000000008
LIQUIDATION_DISCOUNT = 40000000000000000
MIN_RATE = 31709791
MAX_RATE = 317097919837
SUPPLY_LIMIT = 2**256 - 1

OBSERVATIONS = 20
INTERVAL = 30
CHAIN_ID = 10


def _load_account(name: str) -> Account:
    """Decrypt a keystore from ~/.secrets/<name>.json."""
    path = Path.home() / ".secrets" / f"{name}.json"
    with open(path) as f:
        pkey = Account.decrypt(json.load(f), getpass(f"Password for {name}: "))
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


def _deploy(deployer: str, dry_run: bool, report_path: Path, existing_path: Path) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    existing = json.loads(existing_path.read_text())
    factory = boa.load_partial("curve_stablecoin/lending/LendFactory.vy").at(
        existing["factory"]
    )
    print("Factory (existing):", factory.address)

    monetary_policy = boa.load_partial(
        "curve_stablecoin/mpolicies/SemilogMonetaryPolicy.vy"
    ).deploy(LLV2USD, MIN_RATE, MAX_RATE, factory.address)

    solcx.install_solc("0.8.25")
    solcx.set_solc_version("0.8.25")
    oracle = boa.load_partial_solc("scripts/solidity/ChainlinkEMA.sol").deploy(
        CHAINLINK_FEED,
        OBSERVATIONS,
        INTERVAL,
    )

    deployed = factory.create(
        LLV2USD,
        LLV2ETH,
        A,
        FEE,
        LOAN_DISCOUNT,
        LIQUIDATION_DISCOUNT,
        oracle.address,
        monetary_policy.address,
        "LLv2 USD/LLv2 ETH",
        SUPPLY_LIMIT,
        sender=deployer,
    )

    chain_id = CHAIN_ID
    if hasattr(boa.env, "get_chain_id"):
        chain_id = boa.env.get_chain_id()

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
            "borrowed_token": LLV2USD,
            "collateral_token": LLV2ETH,
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
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("Monetary Policy:", monetary_policy.address)
    print("Price Oracle:", oracle.address)
    print("Vault:", deployed[0])
    print("Controller:", deployed[1])
    print("AMM:", deployed[2])
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy LlamaLend on OP")
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--account",
        default=os.environ.get("DEPLOYER_ACCOUNT"),
        help="Keystore name under ~/.secrets/<name>.json",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend-op-testing-fake-token.jsonc",
        help="Where to write the deployment report",
    )
    parser.add_argument(
        "--existing-deployment",
        default="deployments/llamalend-op-testing.jsonc",
        help="Existing deployment JSON to read factory address from",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")

    report_path = Path(args.report_path)
    existing_path = Path(args.existing_deployment)

    if args.dry_run:
        if not args.account:
            raise SystemExit("Missing --account or DEPLOYER_ACCOUNT for dry-run address")
        deployer = _load_account(args.account).address
        with boa.fork(args.rpc_url):
            _deploy(deployer, dry_run=True, report_path=report_path, existing_path=existing_path)
    else:
        if not args.account:
            raise SystemExit("Missing --account or DEPLOYER_ACCOUNT")
        acct = _load_account(args.account)
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _deploy(acct.address, dry_run=False, report_path=report_path, existing_path=existing_path)


if __name__ == "__main__":
    main()
