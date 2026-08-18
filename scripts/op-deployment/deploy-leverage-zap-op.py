#!/usr/bin/env python3

import argparse
import json
import os
import time
from getpass import getpass
from pathlib import Path

import boa
from vyper.compiler.settings import OptimizationLevel
import requests
from boa.network import NetworkEnv
from boa.rpc import EthereumRPC
from eth_account import Account


CHAIN_ID = 10

# LlamaLend V2 lend factory on Optimism (see deployments/op/llamalend-op.jsonc)
OP_LEND_FACTORY = "0x5F94073E3f51c1FFf92ffc6b4B06b7Af193B3640"

# Whitelisted aggregator routers/pools the zap is allowed to call on Optimism
OP_EXCHANGES = [
    "0x0DCDED3545D565bA3B19E683431381007245d983",  # curve-js
    "0x0D05a7D3448512B78fa8A9e46c4872C88C4a0D05",  # odos
    "0xF75584eF6673aD213a685a1B58Cc0330B8eA22Cf",  # enso
]


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
    deployer: str, factory: str, exchanges: list, dry_run: bool, report_path: Path
) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    leverage_zap = boa.load_partial(
        "curve_stablecoin/zaps/LeverageZapLend.vy",
        compiler_args={"optimize": OptimizationLevel.CODESIZE},
    ).deploy(factory, exchanges)

    chain_id = CHAIN_ID
    if hasattr(boa.env, "get_chain_id"):
        chain_id = boa.env.get_chain_id()

    report = {
        "chain_id": chain_id,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "factory": factory,
        "exchanges": exchanges,
        "leverage_zap": leverage_zap.address,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("Factory:", factory)
    print("Exchanges:", exchanges)
    print("LeverageZap:", leverage_zap.address)
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy LlamaLend V2 LeverageZap on OP"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keystore",
        default=os.environ.get("DEPLOYER_KEYSTORE"),
        help="Path to keystore JSON file",
    )
    parser.add_argument(
        "--factory",
        default=OP_LEND_FACTORY,
        help="Lend factory address the zap is associated with",
    )
    parser.add_argument(
        "--exchanges",
        default=",".join(OP_EXCHANGES),
        help="Comma-separated list of whitelisted exchange addresses",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/op/leverage-zap-op.jsonc",
        help="Where to write the deployment report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")

    exchanges = [a.strip() for a in args.exchanges.split(",") if a.strip()]
    report_path = Path(args.report_path)

    if args.dry_run:
        if not args.keystore:
            raise SystemExit(
                "Missing --keystore or DEPLOYER_KEYSTORE for dry-run address"
            )
        deployer = _load_account(args.keystore).address
        with boa.fork(args.rpc_url):
            _deploy(
                deployer, args.factory, exchanges, dry_run=True, report_path=report_path
            )
    else:
        if not args.keystore:
            raise SystemExit("Missing --keystore or DEPLOYER_KEYSTORE")
        acct = _load_account(args.keystore)
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _deploy(
                acct.address,
                args.factory,
                exchanges,
                dry_run=False,
                report_path=report_path,
            )


if __name__ == "__main__":
    main()
