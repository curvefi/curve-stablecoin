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
MAINNET_DAO_AND_EMERGENCY = "0xb7400D2EA0f6DC1d7b153aA430B9E572F28afB79"
MAINNET_DAO_FEE_RECEIVER = "0xeCb456EA5365865EbAb8a2661B0c503410e9B347"

MAINNET_EXCHANGES = [
    "0x45312ea0eFf7E09C83CBE249fa1d7598c4C8cd4e",  # curve-js
    "0x0D05a7D3448512B78fa8A9e46c4872C88C4a0D05",  # odos
    "0xF75584eF6673aD213a685a1B58Cc0330B8eA22Cf",  # enso
    "0xa1c7a8360eb4049595a24d6919e74e105b409cb5",  # curve solver
]


def _load_account(fname: str) -> account.LocalAccount:
    path = os.path.expanduser(os.path.join('~', '.brownie', 'accounts', fname + '.json'))
    with open(path, 'r') as f:
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


def _deploy(deployer: str, dry_run: bool, report_path: Path) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    amm_blueprint = boa.load_partial(
        "curve_stablecoin/AMM.vy",
        compiler_args={"optimize": OptimizationLevel.CODESIZE},
    ).deploy_as_blueprint()
    controller_blueprint = boa.load_partial(
        "curve_stablecoin/lending/LendController.vy",
        compiler_args={"optimize": OptimizationLevel.CODESIZE},
    ).deploy_as_blueprint()
    vault_blueprint = boa.load_partial(
        "curve_stablecoin/lending/Vault.vy"
    ).deploy_as_blueprint()
    controller_view_blueprint = boa.load_partial(
        "curve_stablecoin/lending/LendControllerView.vy",
        compiler_args={"optimize": OptimizationLevel.CODESIZE},
    ).deploy_as_blueprint()

    configurator = boa.load_partial("curve_stablecoin/Configurator.vy").deploy(
        MAINNET_DAO_AND_EMERGENCY
    )

    factory = boa.load_partial("curve_stablecoin/lending/LendFactory.vy").deploy(
        amm_blueprint.address,
        controller_blueprint.address,
        vault_blueprint.address,
        controller_view_blueprint.address,
        configurator.address,
        MAINNET_DAO_AND_EMERGENCY,
        MAINNET_DAO_FEE_RECEIVER,
    )

    leverage_zap = boa.load_partial("curve_stablecoin/zaps/LeverageZapLend.vy").deploy(
        factory.address, MAINNET_EXCHANGES
    )

    chain_id = CHAIN_ID
    if hasattr(boa.env, "get_chain_id"):
        chain_id = boa.env.get_chain_id()

    contracts = {
        "amm_blueprint": amm_blueprint.address,
        "controller_blueprint": controller_blueprint.address,
        "vault_blueprint": vault_blueprint.address,
        "controller_view_blueprint": controller_view_blueprint.address,
        "configurator": configurator.address,
        "factory": factory.address,
        "leverage_zap": leverage_zap.address,
    }

    report = {
        "chain_id": chain_id,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "contracts": contracts,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("Deployed contracts:")
    for name, address in contracts.items():
        print(f"  {name}: {address}")
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy LlamaLend V2 on Mainnet")
    parser.add_argument("--rpc-url", default=os.environ.get("MAINNET_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--account-name",
        default=os.environ.get("ACCOUNT_NAME"),
        help="Path to keystore JSON file",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/mainnet/llamalend-mainnet.jsonc",
        help="Where to write the deployment report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or MAINNET_RPC_URL")

    report_path = Path(args.report_path)

    if args.dry_run:
        if not args.account_name:
            raise SystemExit(
                "Missing --account-name or ACCOUNT_NAME for dry-run address"
            )
        deployer = _load_account(args.account_name).address
        with boa.fork(args.rpc_url):
            _deploy(deployer, dry_run=True, report_path=report_path)
    else:
        if not args.keystore:
            raise SystemExit("Missing --account-name or ACCOUNT_NAME")
        acct = _load_account(args.keystore)
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _deploy(acct.address, dry_run=False, report_path=report_path)


if __name__ == "__main__":
    main()
