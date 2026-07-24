#!/usr/bin/env python3
"""
Deploy the RateCalculator + HyperbolicDynamicMP for the *existing* sDOLA/crvUSD
LlamaLend V2 market on Ethereum Mainnet (the contracts were fixed and refactored).

Unlike the original market-deploy script, the market already exists, so nothing
is created here and no oracle stack is touched. This deploys, in order:
    1. SDolaRateCalculator(sDOLA)              -> per-second yield rate of collateral
    2. HyperbolicDynamicMP(controller, rate_calculator, curve params...)

The controller is NOT precomputed: it is read from the existing market deployment
report and passed to the monetary policy's constructor (which only stores it, it
does not call it). Curve parameters are kept identical to the original deployment.

This script only deploys the two contracts and prints their addresses; it writes
no report file. Swapping the new monetary policy into the live market is a separate
governance action (the DAO owns the factory/controller), e.g. via
`Configurator.set_monetary_policy(controller, monetary_policy)`.

Run:
    # dry-run against a fork
    MAINNET_RPC_URL=... python scripts/mainnet-deployment/monetary_policies/\
boa-deploy-sDOLA-crvUSD-mp.py --dry-run --account-name <name>

    # broadcast
    MAINNET_RPC_URL=... python scripts/mainnet-deployment/monetary_policies/\
boa-deploy-sDOLA-crvUSD-mp.py --account-name <name>
"""

import argparse
import json
import os
import time
from getpass import getpass
from pathlib import Path

import boa
import requests
from boa.network import NetworkEnv
from boa.rpc import EthereumRPC
from eth_account import account
from eth_utils import to_checksum_address


# --- Tokens ---
SDOLA = "0xb45ad160634c528Cc3D2926d9807104FA3157305"  # collateral (ERC4626 vault)
COLLATERAL = SDOLA

# --- Contract sources ---
RATE_CALCULATOR = (
    "curve_stablecoin/mpolicies/v2/rate_calculators/SDolaRateCalculator.vy"
)
HYPERBOLIC_DYNAMIC_MP = "curve_stablecoin/mpolicies/v2/HyperbolicDynamicMP.vy"

# --- Monetary policy curve (identical to the original sDOLA/crvUSD deployment) ---
TARGET_UTILIZATION = 90 * 10**16  # 90%
LOW_RATIO = 5 * 10**17  # 0.5x base at 0% utilization
HIGH_RATIO = 5 * 10**18  # 5x base at 100% utilization
RATE_SHIFT = 0


def _load_account(fname: str) -> account.LocalAccount:
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


class RetryRPC(EthereumRPC):
    def fetch(self, method, params):
        delay = 1.0
        for attempt in range(6):
            try:
                result = super().fetch(method, params)
                if result is None and method == "eth_getBlockByNumber" and attempt < 5:
                    time.sleep(delay)
                    delay *= 1.5
                    continue
                return result
            except requests.exceptions.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status != 503 or attempt == 5:
                    raise
                time.sleep(delay)
                delay *= 1.5


def _deploy(deployer: str, dry_run: bool, market_deployment: Path) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    # Read the existing market's controller — the monetary policy binds it as an
    # immutable, so it must be the live controller, not a precomputed one.
    existing = json.loads(market_deployment.read_text())
    contracts = existing.get("contracts", existing)
    controller_addr = to_checksum_address(contracts["controller"])
    if "collateral_token" in existing.get("params", {}):
        assert to_checksum_address(
            existing["params"]["collateral_token"]
        ) == to_checksum_address(COLLATERAL), (
            "market deployment collateral does not match sDOLA"
        )

    # 1. Rate calculator reading the live vault.
    rate_calculator = boa.load_partial(RATE_CALCULATOR).deploy(COLLATERAL)

    # 2. Monetary policy, bound to the existing controller.
    monetary_policy = boa.load_partial(HYPERBOLIC_DYNAMIC_MP).deploy(
        controller_addr,
        rate_calculator.address,
        TARGET_UTILIZATION,
        LOW_RATIO,
        HIGH_RATIO,
        RATE_SHIFT,
    )

    # Sanity-check the wiring against the live controller/vault (view calls only).
    target_rate = monetary_policy.target_rate()
    rate = monetary_policy.rate()

    print("Market:", "sDOLA/crvUSD")
    print("Controller (existing):", controller_addr)
    print("Rate Calculator:", rate_calculator.address)
    print("Monetary Policy:", monetary_policy.address)
    print(
        "  params: target_util=%s low_ratio=%s high_ratio=%s rate_shift=%s"
        % (TARGET_UTILIZATION, LOW_RATIO, HIGH_RATIO, RATE_SHIFT)
    )
    print("  target_rate (per sec):", target_rate)
    print("  rate() (per sec):", rate)
    print()
    print(
        "Next step (governance): Configurator.set_monetary_policy(%s, %s)"
        % (controller_addr, monetary_policy.address)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Redeploy sDOLA/crvUSD RateCalculator + HyperbolicDynamicMP on Mainnet"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("MAINNET_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--account-name",
        default=os.environ.get("ACCOUNT_NAME"),
        help="Brownie account name",
    )
    parser.add_argument(
        "--market-deployment",
        default="deployments/mainnet/markets/llamalend-mainnet-sDOLA-crvUSD.jsonc",
        help="Existing market deployment JSON to read the controller address from",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or MAINNET_RPC_URL")

    market_deployment = Path(args.market_deployment)
    if not market_deployment.exists():
        raise SystemExit(f"Market deployment not found: {market_deployment}")

    if not args.account_name:
        raise SystemExit("Missing --account-name or ACCOUNT_NAME")

    if args.dry_run:
        deployer = _load_account(args.account_name).address
        with boa.fork(args.rpc_url):
            _deploy(deployer, dry_run=True, market_deployment=market_deployment)
    else:
        acct = _load_account(args.account_name)
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _deploy(acct.address, dry_run=False, market_deployment=market_deployment)


if __name__ == "__main__":
    main()
