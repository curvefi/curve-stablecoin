#!/usr/bin/env python3
"""
Deploy a HyperbolicMP monetary policy for the wstETH/USDC LlamaLend market on Optimism.

HyperbolicMP is a fixed-target-rate policy with a hyperbolic rate curve. Its
Controller is an immutable set in the constructor, so this script binds it to the
*existing* wstETH/USDC market controller (read from the market's deployment file).

This only deploys the policy; wiring it into the controller (set_monetary_policy)
is a separate factory-admin / DAO action and is intentionally not done here.

All curve parameters are left as TODOs and must be filled in before running; a
guard in _deploy() aborts before touching the chain.

Run:
    # dry-run against a fork
    OP_RPC_URL=... python scripts/op-deployment/\
boa-deploy-hyperbolic-mp-op-wstETH-USDC.py --dry-run --keystore <path>

    # broadcast
    OP_RPC_URL=... python scripts/op-deployment/\
boa-deploy-hyperbolic-mp-op-wstETH-USDC.py --keystore <path>
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
from eth_account import Account


HYPERBOLIC_MP = "curve_stablecoin/mpolicies/v2/HyperbolicMP.vy"

# --- HyperbolicMP curve parameters ---
TARGET_UTILIZATION = 85 * 10**16  # 85%
TARGET_RATE = 5 * 10**16 // (365 * 86400)  # ~5% APR (per second, 1e18-scaled)
LOW_RATIO = 10**17  # 0.1x base at 0% utilization
HIGH_RATIO = 60 * 10**18  # 60x base at 100% utilization
RATE_SHIFT = 0  # no flat shift

_REQUIRED_PARAMS = {
    "TARGET_UTILIZATION": TARGET_UTILIZATION,
    "TARGET_RATE": TARGET_RATE,
    "LOW_RATIO": LOW_RATIO,
    "HIGH_RATIO": HIGH_RATIO,
    "RATE_SHIFT": RATE_SHIFT,
}


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
    missing = [k for k, v in _REQUIRED_PARAMS.items() if v is None]
    assert not missing, f"Fill in TODO params before deploying: {missing}"

    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    existing = json.loads(market_deployment.read_text())
    controller = existing.get("controller") or existing["contracts"]["controller"]

    monetary_policy = boa.load_partial(HYPERBOLIC_MP).deploy(
        controller,
        TARGET_UTILIZATION,
        TARGET_RATE,
        LOW_RATIO,
        HIGH_RATIO,
        RATE_SHIFT,
    )

    print("Market: wstETH/USDC (Optimism)")
    print("Controller:", controller)
    print("Monetary Policy (HyperbolicMP):", monetary_policy.address)
    print("Target APR:", monetary_policy.target_apr() / 10**18)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy HyperbolicMP for wstETH/USDC on Optimism"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keystore",
        default=os.environ.get("DEPLOYER_KEYSTORE"),
        help="Path to keystore JSON file",
    )
    parser.add_argument(
        "--market-deployment",
        default="deployments/op/llamalend-op-wstETH-USDC.jsonc",
        help="Path to the existing market deployment JSON to read the controller from",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")

    market_deployment = Path(args.market_deployment)
    if not market_deployment.exists():
        raise SystemExit(f"Market deployment not found: {market_deployment}")

    if not args.keystore:
        raise SystemExit("Missing --keystore or DEPLOYER_KEYSTORE")

    if args.dry_run:
        deployer = _load_account(args.keystore).address
        with boa.fork(args.rpc_url):
            _deploy(deployer, dry_run=True, market_deployment=market_deployment)
    else:
        acct = _load_account(args.keystore)
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _deploy(acct.address, dry_run=False, market_deployment=market_deployment)


if __name__ == "__main__":
    main()
