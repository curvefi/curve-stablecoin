#!/usr/bin/env python3

import argparse
import json
import os
from getpass import getpass
from pathlib import Path
from typing import Any

import boa
from boa.network import NetworkEnv
from boa.rpc import EthereumRPC
from eth_account import Account

WAD = 10**18
# llv2-USD (borrowed / supply token, 18 decimals)
DEPOSIT_USD = 1_000 * WAD   # USD deposited into vault as liquidity
BORROW_USD  =   500 * WAD   # USD borrowed against ETH collateral
REPAY_USD   =   100 * WAD   # USD repaid
# llv2-ETH (collateral token, 18 decimals)
COLLATERAL_ETH = 1 * WAD    # ETH posted as collateral
N_BANDS = 10
MAX_UINT256 = 2**256 - 1

def _load_account(name: str) -> Account:
    """Decrypt a keystore from ~/.secrets/<name>.json."""
    path = Path.home() / ".secrets" / f"{name}.json"
    with open(path) as f:
        pkey = Account.decrypt(json.load(f), getpass(f"Password for {name}: "))
    return Account.from_key(pkey)


ERC20_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "_spender", "type": "address"},
            {"internalType": "uint256", "name": "_amount", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "nonpayable",
        "type": "function",
    }
]


def load_deployment(report_path: Path) -> dict[str, Any]:
    try:
        return json.loads(report_path.read_text())
    except FileNotFoundError as exc:
        raise SystemExit(f"Deployment report not found: {report_path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in deployment report: {report_path}") from exc


def load_contracts(deployment: dict[str, Any]) -> dict[str, Any]:
    return {
        "vault": boa.load_partial("curve_stablecoin/lending/Vault.vy").at(
            deployment["vault"]
        ),
        "controller": boa.load_partial("curve_stablecoin/lending/LendController.vy").at(
            deployment["controller"]
        ),
        "amm": boa.load_partial("curve_stablecoin/AMM.vy").at(deployment["amm"]),
    }


def load_tokens(
    borrowed_token_address: str, collateral_token_address: str
) -> dict[str, Any]:
    erc20 = boa.loads_abi(json.dumps(ERC20_ABI), name="IERC20")
    return {
        "borrowed_token": erc20.at(borrowed_token_address),
        "collateral_token": erc20.at(collateral_token_address),
    }


def _open_position(deployer: str, dry_run: bool, report_path: Path) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    deployment = load_deployment(report_path)
    contracts = load_contracts(deployment)
    tokens = load_tokens(
        deployment["params"]["borrowed_token"],
        deployment["params"]["collateral_token"],
    )

    # 1) deposit llv2-USD into vault as liquidity
    tokens["borrowed_token"].approve(
        contracts["vault"].address, DEPOSIT_USD, sender=deployer
    )
    contracts["vault"].deposit(DEPOSIT_USD, deployer, sender=deployer)

    # 2) long ETH: post llv2-ETH collateral and borrow llv2-USD
    # contracts["controller"].set_borrow_cap(MAX_UINT256, sender=deployer)
    tokens["collateral_token"].approve(
        contracts["controller"].address, COLLATERAL_ETH, sender=deployer
    )
    contracts["controller"].create_loan(
        COLLATERAL_ETH, BORROW_USD, N_BANDS, sender=deployer
    )

    # 3) repay partial llv2-USD debt
    tokens["borrowed_token"].approve(
        contracts["controller"].address, REPAY_USD, sender=deployer
    )
    contracts["controller"].repay(REPAY_USD, sender=deployer)

    print("Loaded contracts from:", report_path)
    for name, contract in contracts.items():
        print(f"{name}: {contract.address}")
    print("Vault deposit (llv2-USD):", DEPOSIT_USD / WAD, "USD")
    print("Collateral (llv2-ETH):", COLLATERAL_ETH / WAD, "ETH")
    print("Borrowed (llv2-USD):", BORROW_USD / WAD, "USD")
    print("Repaid (llv2-USD):", REPAY_USD / WAD, "USD")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open a LlamaLend OP position using pre-funded wallet token balances"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument(
        "--account",
        default=os.environ.get("DEPLOYER_ACCOUNT"),
        help="Keystore name under ~/.secrets/<name>.json",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend-op-testing-fake-token.jsonc",
        help="Deployment report produced by scripts/boa-deploy-llamalend-op.py",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")
    if not args.account:
        raise SystemExit("Missing --account or DEPLOYER_ACCOUNT")

    report_path = Path(args.report_path)
    acct = _load_account(args.account)

    if args.dry_run:
        with boa.fork(args.rpc_url):
            _open_position(acct.address, dry_run=True, report_path=report_path)
    else:
        with boa.set_env(NetworkEnv(EthereumRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _open_position(acct.address, dry_run=False, report_path=report_path)


if __name__ == "__main__":
    main()
