#!/usr/bin/env python3
"""
Deploy replacement ChainlinkEMA price oracles for the *existing* LlamaLend V2 markets
on Optimism (WBTC/USDC, wstETH/USDC, wstETH/WETH).

The live markets run an earlier ChainlinkEMA revision (no phase-switch or per-phase
decimals handling). This deploys one oracle per market from the current source, using
the same Chainlink feed, OBSERVATIONS and INTERVAL as the market's deployment report,
and checks each new price against the market's current oracle.

Nothing is wired here: swapping an oracle into a market is a governance action (the
DAO owns the Configurator), done per market with
`Configurator.set_price_oracle(controller, oracle, max_deviation)`.

Run:
    # dry-run against a fork (no report is written)
    OP_RPC_URL=... python scripts/deploy/llamalend/optimism/oracles/deploy.py --dry-run

    # broadcast
    OP_RPC_URL=... python scripts/deploy/llamalend/optimism/oracles/deploy.py --keystore <path>
"""

import argparse
import json
import os
import time
from getpass import getpass
from pathlib import Path

import boa
import boa_solidity  # noqa: F401
import requests
import solcx
from boa.network import NetworkEnv
from boa.rpc import EthereumRPC
from eth_account import Account


CHAINLINK_EMA = "scripts/deploy/llamalend/optimism/solidity/ChainlinkEMA.sol"
MARKETS = ["WBTC-USDC", "wstETH-USDC", "wstETH-WETH"]
MARKET_DEPLOYMENTS = "deployments/llamalend/optimism/markets"
CONFIGURATOR = "0xd36c590531cAF5F620C57Faf5827Ce8E7f6E5Bec"

# Configurator.set_price_oracle rejects a new oracle whose price is further than this
# from the current one; the new oracle reads the same feed, so it should be far closer
MAX_DEVIATION = 10**16  # 1%

_AMM_ABI = """[
    {"name": "price_oracle_contract", "inputs": [], "outputs": [{"type": "address"}],
     "stateMutability": "view", "type": "function"}
]"""
_ORACLE_ABI = """[
    {"name": "price", "inputs": [], "outputs": [{"type": "uint256"}],
     "stateMutability": "view", "type": "function"}
]"""
_FEED_ABI = """[
    {"name": "decimals", "inputs": [], "outputs": [{"type": "uint8"}],
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


def _deploy(deployer: str, dry_run: bool, report_path: Path) -> dict:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    solcx.install_solc("0.8.25")
    solcx.set_solc_version("0.8.25")
    chainlink_ema = boa.load_partial_solc(CHAINLINK_EMA)

    report = {
        "chain_id": 10,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "source": CHAINLINK_EMA,
        "oracles": {},
    }
    for market in MARKETS:
        existing = json.loads(Path(f"{MARKET_DEPLOYMENTS}/{market}.jsonc").read_text())
        params = existing["params"]
        feed = params["chainlink_feed"]
        observations = params["observations"]
        interval = params["interval"]

        oracle = chainlink_ema.deploy(feed, observations, interval)

        # the market's current oracle, read from the AMM rather than the report
        amm = boa.loads_abi(_AMM_ABI).at(existing["amm"])
        current = boa.loads_abi(_ORACLE_ABI).at(amm.price_oracle_contract())
        old_price = current.price()
        new_price = oracle.price()
        deviation = abs(new_price - old_price) * 10**18 // old_price
        assert deviation <= MAX_DEVIATION, (
            f"{market}: new price deviates {deviation / 1e16}%"
        )

        decimals = boa.loads_abi(_FEED_ABI).at(feed).decimals()
        assert oracle.storedResponse()[2] == decimals, f"{market}: decimals mismatch"

        report["oracles"][market] = {
            "price_oracle": oracle.address,
            "replaces": current.address,
            "controller": existing["controller"],
            "chainlink_feed": feed,
            "observations": observations,
            "interval": interval,
        }
        print(f"Market: {market}")
        print(f"  ChainlinkEMA: {oracle.address} (replaces {current.address})")
        print(f"  feed: {feed}, decimals: {decimals}")
        print(
            f"  price: {new_price} (current {old_price}, deviation {deviation / 1e16:.4f}%)"
        )

    if dry_run:
        print("\nDry run, report not written:")
        print(json.dumps(report, indent=2))
    else:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print("\nReport:", report_path)

    print(f"\nNext step (governance), on Configurator {CONFIGURATOR}:")
    for market, entry in report["oracles"].items():
        print(
            f"  set_price_oracle({entry['controller']}, {entry['price_oracle']}, "
            f"{MAX_DEVIATION})  # {market}"
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy replacement ChainlinkEMA oracles for the LlamaLend markets on OP"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keystore",
        default=os.environ.get("DEPLOYER_KEYSTORE"),
        help="Path to keystore JSON file (optional for a dry run)",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend/optimism/oracles.jsonc",
        help="Where to write the deployment report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")

    report_path = Path(args.report_path)

    if args.dry_run:
        if args.keystore:
            deployer = _load_account(args.keystore).address
        else:
            deployer = boa.env.generate_address("deployer")
        with boa.fork(args.rpc_url):
            _deploy(deployer, dry_run=True, report_path=report_path)
    else:
        if not args.keystore:
            raise SystemExit("Missing --keystore or DEPLOYER_KEYSTORE")
        acct = _load_account(args.keystore)
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _deploy(acct.address, dry_run=False, report_path=report_path)


if __name__ == "__main__":
    main()
