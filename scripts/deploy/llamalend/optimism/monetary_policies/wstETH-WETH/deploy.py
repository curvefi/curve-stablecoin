#!/usr/bin/env python3
"""
Deploy the WstETHRateCalculator + HyperbolicDynamicMP for the *existing* wstETH/WETH
LlamaLend V2 market on Optimism, replacing its EMAMonetaryPolicy and
wstETHRateCalculator.

Unlike the original market-deploy script, the market already exists, so nothing
is created here and no oracle is touched. This deploys, in order:
    1. WstETHRateCalculator(Lido TokenRateOracle, avg_window) -> per-second wstETH yield
    2. HyperbolicDynamicMP(controller, rate_calculator, curve params...)

The controller, the Lido oracle, the averaging window and the curve parameters are
read from the existing market deployment report, so they are identical to the
original deployment.

Swapping the new monetary policy into the live market is a separate governance
action (the DAO owns the Configurator), e.g. via
`Configurator.set_monetary_policy(controller, monetary_policy)`.

Run:
    # dry-run against a fork (no report is written)
    OP_RPC_URL=... python scripts/deploy/llamalend/optimism/monetary_policies/\
wstETH-WETH/deploy.py --dry-run

    # broadcast
    OP_RPC_URL=... python scripts/deploy/llamalend/optimism/monetary_policies/\
wstETH-WETH/deploy.py --keystore <path>
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


RATE_CALCULATOR = (
    "curve_stablecoin/mpolicies/v2/rate_calculators/WstETHRateCalculator.vy"
)
HYPERBOLIC_DYNAMIC_MP = "curve_stablecoin/mpolicies/v2/HyperbolicDynamicMP.vy"
CONFIGURATOR = "0xd36c590531cAF5F620C57Faf5827Ce8E7f6E5Bec"
YEAR = 365 * 86400

_AMM_ABI = """[
    {"name": "rate", "inputs": [], "outputs": [{"type": "uint256"}],
     "stateMutability": "view", "type": "function"}
]"""
_RATE_CALCULATOR_ABI = """[
    {"name": "rate", "inputs": [], "outputs": [{"type": "uint256"}],
     "stateMutability": "view", "type": "function"}
]"""


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


def _deploy(
    deployer: str, dry_run: bool, market_deployment: Path, report_path: Path
) -> dict:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    existing = json.loads(market_deployment.read_text())
    params = existing["params"]
    controller = existing["controller"]

    # 1. Rate calculator reading Lido's wstETH rate oracle.
    rate_calculator = boa.load_partial(RATE_CALCULATOR).deploy(
        params["wsteth_rate_oracle"], params["avg_window"]
    )

    # 2. Monetary policy, bound to the existing controller.
    monetary_policy = boa.load_partial(HYPERBOLIC_DYNAMIC_MP).deploy(
        controller,
        rate_calculator.address,
        params["target_utilization"],
        params["low_ratio"],
        params["high_ratio"],
        params["rate_shift"],
    )

    # The new calculator must report the same yield as the one it replaces.
    old_calculator = boa.loads_abi(_RATE_CALCULATOR_ABI).at(existing["rate_calculator"])
    assert rate_calculator.rate() == old_calculator.rate(), "rate calculator mismatch"

    current_rate = boa.loads_abi(_AMM_ABI).at(existing["amm"]).rate()
    new_rate = monetary_policy.rate()

    report = {
        "chain_id": 10,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "rate_calculator": rate_calculator.address,
        "monetary_policy": monetary_policy.address,
        "replaces": {
            "rate_calculator": existing["rate_calculator"],
            "monetary_policy": existing["monetary_policy"],
        },
        "controller": controller,
        "params": {
            "wsteth_rate_oracle": params["wsteth_rate_oracle"],
            "avg_window": params["avg_window"],
            "target_utilization": params["target_utilization"],
            "low_ratio": params["low_ratio"],
            "high_ratio": params["high_ratio"],
            "rate_shift": params["rate_shift"],
        },
    }

    print("Market: wstETH/WETH (Optimism)")
    print("Controller (existing):", controller)
    print("Rate Calculator:", rate_calculator.address)
    print("Monetary Policy:", monetary_policy.address)
    print(
        "  params: target_util=%s low_ratio=%s high_ratio=%s rate_shift=%s"
        % (
            params["target_utilization"],
            params["low_ratio"],
            params["high_ratio"],
            params["rate_shift"],
        )
    )
    print(
        f"  target_rate: {monetary_policy.target_rate()} ({monetary_policy.target_apr() / 1e16:.2f}% APR)"
    )
    print(f"  rate(): {new_rate} ({new_rate * YEAR / 1e16:.2f}% APR)")
    print(
        f"  current market rate: {current_rate} ({current_rate * YEAR / 1e16:.2f}% APR)"
    )

    if dry_run:
        print("\nDry run, report not written:")
        print(json.dumps(report, indent=2))
    else:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print("\nReport:", report_path)

    print(
        f"\nNext step (governance), on Configurator {CONFIGURATOR}:\n"
        f"  set_monetary_policy({controller}, {monetary_policy.address})"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy wstETH/WETH WstETHRateCalculator + HyperbolicDynamicMP on Optimism"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keystore",
        default=os.environ.get("DEPLOYER_KEYSTORE"),
        help="Path to keystore JSON file (optional for a dry run)",
    )
    parser.add_argument(
        "--market-deployment",
        default="deployments/llamalend/optimism/markets/wstETH-WETH.jsonc",
        help="Existing market deployment JSON to read the controller and parameters from",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend/optimism/monetary_policies/wstETH-WETH.jsonc",
        help="Where to write the deployment report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")

    market_deployment = Path(args.market_deployment)
    if not market_deployment.exists():
        raise SystemExit(f"Market deployment not found: {market_deployment}")
    report_path = Path(args.report_path)

    if args.dry_run:
        if args.keystore:
            deployer = _load_account(args.keystore).address
        else:
            deployer = boa.env.generate_address("deployer")
        with boa.fork(args.rpc_url):
            _deploy(deployer, True, market_deployment, report_path)
    else:
        if not args.keystore:
            raise SystemExit("Missing --keystore or DEPLOYER_KEYSTORE")
        acct = _load_account(args.keystore)
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _deploy(acct.address, False, market_deployment, report_path)


if __name__ == "__main__":
    main()
