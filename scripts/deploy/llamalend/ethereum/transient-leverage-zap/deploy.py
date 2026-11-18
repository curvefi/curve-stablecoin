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
from eth_account import account


CHAIN_ID = 1

# LlamaLend V2 lend factory on Ethereum (see deployments/llamalend/ethereum/factory.jsonc)
MAINNET_LEND_FACTORY = "0x8f6B56EC5ddF1F2691a1059f1D3cd97Ac9EaB0bd"

# Whitelisted aggregator routers/pools the zap is allowed to call on Ethereum
MAINNET_EXCHANGES = [
    "0x45312ea0eFf7E09C83CBE249fa1d7598c4C8cd4e",  # curve-js
    "0xF75584eF6673aD213a685a1B58Cc0330B8eA22Cf",  # enso
    "0xa1c7a8360eb4049595a24d6919e74e105b409cb5",  # curve solver
    "0x0000000000001fF3684f28c67538d4D072C22734",  # 0x
    "0x6131B5fae19EA4f9D964eAc0408E4408b66337b5",  # KyberSwap
]


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


def _deploy(
    deployer: str, factory: str, exchanges: list, dry_run: bool, report_path: Path
) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    leverage_zap = boa.load_partial(
        "curve_stablecoin/zaps/transient_leverage_zap/TransientLeverageZapLend.vy",
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
        "transient_leverage_zap": leverage_zap.address,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("Factory:", factory)
    print("Exchanges:", exchanges)
    print("TransientLeverageZapLend:", leverage_zap.address)
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy LlamaLend V2 TransientLeverageZapLend on Ethereum"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("MAINNET_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--account-name",
        default=os.environ.get("ACCOUNT_NAME"),
        help="Brownie account name",
    )
    parser.add_argument(
        "--factory",
        default=MAINNET_LEND_FACTORY,
        help="Lend factory address the zap is associated with",
    )
    parser.add_argument(
        "--exchanges",
        default=",".join(MAINNET_EXCHANGES),
        help="Comma-separated list of whitelisted exchange addresses",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend/ethereum/transient-leverage-zap.jsonc",
        help="Where to write the deployment report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or MAINNET_RPC_URL")

    exchanges = [a.strip() for a in args.exchanges.split(",") if a.strip()]
    report_path = Path(args.report_path)

    if args.dry_run:
        if not args.account_name:
            raise SystemExit(
                "Missing --account-name or ACCOUNT_NAME for dry-run address"
            )
        deployer = _load_account(args.account_name).address
        with boa.fork(args.rpc_url):
            _deploy(
                deployer, args.factory, exchanges, dry_run=True, report_path=report_path
            )
    else:
        if not args.account_name:
            raise SystemExit("Missing --account-name or ACCOUNT_NAME")
        acct = _load_account(args.account_name)
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
