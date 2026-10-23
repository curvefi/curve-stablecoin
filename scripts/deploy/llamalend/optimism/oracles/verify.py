#!/usr/bin/env python3
"""Verify the replacement ChainlinkEMA oracles on Optimism Etherscan.

Companion to deploy.py: reads the oracle addresses and constructor arguments from
the report it writes (deployments/llamalend/optimism/oracles.jsonc).

Run:
    ETHERSCAN_API_KEY=... python scripts/deploy/llamalend/optimism/oracles/verify.py
"""

import argparse
import json
import os
import time
from pathlib import Path

import requests
import solcx
from eth_abi import encode

PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_REPORT = "deployments/llamalend/optimism/oracles.jsonc"

# ---------------------------------------------------------------------------
# Standard JSON builder
# ---------------------------------------------------------------------------


def _build_solidity_json(sol_path: Path) -> dict:
    solcx.install_solc("0.8.25")
    solcx.set_solc_version("0.8.25")
    source_key = sol_path.name
    return {
        "language": "Solidity",
        "sources": {source_key: {"content": sol_path.read_text()}},
        "settings": {
            "optimizer": {"enabled": False, "runs": 200},
            "evmVersion": "cancun",
            "outputSelection": {
                source_key: {"*": ["abi", "evm.bytecode", "evm.deployedBytecode"]}
            },
        },
    }


# ---------------------------------------------------------------------------
# Etherscan submit / poll
# ---------------------------------------------------------------------------

ETHERSCAN_API = "https://api.etherscan.io/v2/api"
CHAIN_ID = "10"


def _get_creation_txhash(api_key: str, address: str) -> str | None:
    resp = requests.get(
        ETHERSCAN_API,
        params={
            "chainid": CHAIN_ID,
            "apikey": api_key,
            "module": "contract",
            "action": "getcontractcreation",
            "contractaddresses": address,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") == "1" and data.get("result"):
        txhash = data["result"][0].get("txHash")
        if txhash:
            return txhash
    return None


def _submit(
    api_key: str,
    address: str,
    contract_name: str,
    std_json: dict,
    constructor_args: str,
    compiler_version: str,
    codeformat: str,
    optimization_used: str = "1",
    txhash: str | None = None,
) -> str:
    payload = {
        "apikey": api_key,
        "module": "contract",
        "action": "verifysourcecode",
        "contractaddress": address,
        "sourceCode": json.dumps(std_json),
        "codeformat": codeformat,
        "contractname": contract_name,
        "compilerversion": compiler_version,
        "optimizationUsed": optimization_used,
        "constructorArguements": constructor_args,
    }
    if txhash:
        payload["txhash"] = txhash
    resp = requests.post(
        ETHERSCAN_API,
        params={"chainid": CHAIN_ID},
        data=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data.get("result", "")
    if data.get("status") != "1":
        if "already verified" in result.lower():
            return "already_verified"
        raise RuntimeError(f"Etherscan submit failed: {result}")
    return result


def _poll(api_key: str, guid: str, label: str) -> None:
    print(f"  Polling {label}...", end="", flush=True)
    for _ in range(60):
        time.sleep(5)
        resp = requests.get(
            ETHERSCAN_API,
            params={
                "chainid": CHAIN_ID,
                "apikey": api_key,
                "module": "contract",
                "action": "checkverifystatus",
                "guid": guid,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", "")
        if "Pending" in result or result == "0":
            print(".", end="", flush=True)
            continue
        if "Pass" in result or data.get("status") == "1":
            print(" Verified")
            return
        if "Already Verified" in result:
            print(" Already verified")
            return
        raise RuntimeError(f"Etherscan verification failed: {result}")
    raise RuntimeError("Verification timed out")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the replacement ChainlinkEMA oracles on Optimism Etherscan"
    )
    parser.add_argument(
        "--report", default=DEFAULT_REPORT, help="Report written by deploy.py"
    )
    args = parser.parse_args()

    api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not api_key:
        raise SystemExit("Missing ETHERSCAN_API_KEY")

    report_path = Path(args.report)
    if not report_path.is_absolute():
        report_path = PROJECT_ROOT / report_path
    if not report_path.exists():
        raise SystemExit(f"Report not found: {report_path}")
    report = json.loads(report_path.read_text())

    std_json = _build_solidity_json(PROJECT_ROOT / report["source"])
    for market, entry in report["oracles"].items():
        address = entry["price_oracle"]
        label = f"ChainlinkEMA {market} (Solidity 0.8.25)"
        ctor_hex = encode(
            ["address", "uint256", "uint256"],
            [entry["chainlink_feed"], entry["observations"], entry["interval"]],
        ).hex()

        print(f"\nVerifying {label} at {address}...")
        txhash = _get_creation_txhash(api_key, address)
        if txhash:
            print(f"  creation tx: {txhash}")
        try:
            guid = _submit(
                api_key,
                address,
                "ChainlinkEMA.sol:ChainlinkEMA",
                std_json,
                ctor_hex,
                "v0.8.25+commit.b61c2a91",
                "solidity-standard-json-input",
                "0",
                txhash=txhash,
            )
            if guid == "already_verified":
                print("  Already verified")
            else:
                print(f"  GUID: {guid}")
                _poll(api_key, guid, label)
            print(f"  https://optimistic.etherscan.io/address/{address}#code")
        except RuntimeError as e:
            print(f"  FAILED: {e}")
            print(f"  UNVERIFIED: {label} at {address}")


if __name__ == "__main__":
    main()
