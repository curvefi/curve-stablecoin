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
OP_DAO_OWNERSHIP = "0x28c4A1Fa47EEE9226F8dE7D6AF0a41C62Ca98267"
OP_DAO_FEE_RECEIVER = "0xbF7E49483881C76487b0989CD7d9A8239B20CA41"


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


def _deploy(deployer: str, dry_run: bool, report_path: Path) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    amm_blueprint = boa.load_partial("curve_stablecoin/AMM.vy", compiler_args={"optimize": OptimizationLevel.CODESIZE}).deploy_as_blueprint()
    controller_blueprint = boa.load_partial(
        "curve_stablecoin/lending/LendController.vy", compiler_args={"optimize": OptimizationLevel.CODESIZE}
    ).deploy_as_blueprint()
    vault_blueprint = boa.load_partial(
        "curve_stablecoin/lending/Vault.vy"
    ).deploy_as_blueprint()
    controller_view_blueprint = boa.load_partial(
        "curve_stablecoin/lending/LendControllerView.vy", compiler_args={"optimize": OptimizationLevel.CODESIZE}
    ).deploy_as_blueprint()

    configurator = boa.load_partial("curve_stablecoin/Configurator.vy").deploy(OP_DAO_OWNERSHIP)

    factory = boa.load_partial("curve_stablecoin/lending/LendFactory.vy").deploy(
        amm_blueprint.address,
        controller_blueprint.address,
        vault_blueprint.address,
        controller_view_blueprint.address,
        configurator.address,
        OP_DAO_OWNERSHIP,
        OP_DAO_FEE_RECEIVER,
    )

    leverage_zap = boa.load_partial(
        "curve_stablecoin/zaps/LeverageZapLending.vy"
    ).deploy(factory.address)

    chain_id = CHAIN_ID
    if hasattr(boa.env, "get_chain_id"):
        chain_id = boa.env.get_chain_id()

    report = {
        "chain_id": chain_id,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "factory": factory.address,
        "configurator": configurator.address,
        "leverage_zap": leverage_zap.address,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("Factory:", factory.address)
    print("Configurator:", configurator.address)
    print("LeverageZap:", leverage_zap.address)
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy LlamaLend on OP")
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--keystore",
        default=os.environ.get("DEPLOYER_KEYSTORE"),
        help="Path to keystore JSON file",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend-op.jsonc",
        help="Where to write the deployment report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")

    report_path = Path(args.report_path)

    if args.dry_run:
        if not args.keystore:
            raise SystemExit("Missing --keystore or DEPLOYER_KEYSTORE for dry-run address")
        deployer = _load_account(args.keystore).address
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
