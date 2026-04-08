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

DIGITS = 10**18
SEED_USD = 100000 * DIGITS   # vault liquidity to seed so the borrow can succeed
COLLATERAL_ETH = 1 * DIGITS
BORROW_USD = 1500 * DIGITS
REPAY_USD = 750 * DIGITS
N_BANDS = 10
MAX_UINT256 = 2**256 - 1

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


def _load_account(keystore_path: str) -> Account:
    """Decrypt a keystore file."""
    path = Path(keystore_path)
    with open(path) as f:
        pkey = Account.decrypt(json.load(f), getpass(f"Password for {path.name}: "))
    return Account.from_key(pkey)


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

    # raise borrow cap with deployer key

    # contracts["controller"].set_borrow_cap(200000*DIGITS, sender=deployer)

    # 1) seed the vault with USD liquidity (borrowed_token = LLv2 USD) so borrowing is possible
    tokens["borrowed_token"].approve(
        contracts["vault"].address, SEED_USD, sender=deployer
    )
    contracts["vault"].deposit(SEED_USD, deployer, sender=deployer)

    # 2) borrow 2000 USD worth against collateral (LLv2 ETH)
    # contracts["controller"].set_borrow_cap(MAX_UINT256, sender=deployer)
    tokens["collateral_token"].approve(
        contracts["controller"].address, COLLATERAL_ETH, sender=deployer
    )
    contracts["controller"].create_loan(
        COLLATERAL_ETH, BORROW_USD, N_BANDS, sender=deployer
    )

    # 3) repay 1000 USD of debt
    tokens["borrowed_token"].approve(
        contracts["controller"].address, REPAY_USD, sender=deployer
    )
    contracts["controller"].repay(REPAY_USD, sender=deployer)

    print("Loaded contracts from:", report_path)
    for name, contract in contracts.items():
        print(f"{name}: {contract.address}")
    print("Vault seed deposit (LLv2 USD):", SEED_USD)
    print("Collateral used (LLv2 ETH):", COLLATERAL_ETH)
    print("Borrowed amount:", BORROW_USD)
    print("Repaid amount:", REPAY_USD)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open a LlamaLend OP position in the fake LLv2 ETH/USD market"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend-op-testing-ETH-USD-fake.jsonc",
        help="Deployment report produced by scripts/boa-deploy-llamalend-op-test-all.py",
    )
    parser.add_argument(
        "--keystore",
        default=os.environ.get("DEPLOYER_KEYSTORE"),
        help="Path to keystore JSON file",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")
    if not args.keystore:
        raise SystemExit("Missing --keystore or DEPLOYER_KEYSTORE")

    acct = _load_account(args.keystore)
    report_path = Path(args.report_path)

    if args.dry_run:
        with boa.fork(args.rpc_url):
            _open_position(acct.address, dry_run=True, report_path=report_path)
    else:
        with boa.set_env(NetworkEnv(EthereumRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _open_position(acct.address, dry_run=False, report_path=report_path)


if __name__ == "__main__":
    main()
