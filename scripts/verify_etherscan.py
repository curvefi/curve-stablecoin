"""Verify all three contracts on Etherscan (Optimism, chain 10).

Uses Etherscan API v2 with vyper-json codeformat.
Note: LLv2Token has immutable variables from snekmate; Etherscan may report
'Unable to locate a matching contract' for those due to a known limitation
(Vyper standard JSON omits immutableReferences).  LLv2Faucet has no
immutables and should verify cleanly.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from _env import load_deployment, TOKEN_CONTRACT, FAUCET_CONTRACT

ETHERSCAN_API    = "https://api.etherscan.io/v2/api"
CHAIN_ID         = "10"
COMPILER_VERSION = "vyper:0.4.3"

SNEKMATE = Path(__file__).parent.parent / ".venv/lib/python3.12/site-packages/snekmate"

TOKEN_DEPS = [
    "auth/ownable.vy",
    "tokens/erc20.vy",
    "tokens/interfaces/IERC20Permit.vyi",
    "utils/interfaces/IERC5267.vyi",
    "utils/ecdsa.vy",
    "utils/eip712_domain_separator.vy",
    "utils/message_hash_utils.vy",
]


def _build_std_json(contract_path: Path, snekmate_deps: list[str]) -> dict:
    sources = {f"contracts/{contract_path.name}": {"content": contract_path.read_text()}}
    for rel in snekmate_deps:
        sources[f"snekmate/{rel}"] = {"content": (SNEKMATE / rel).read_text()}
    return {
        "language": "Vyper",
        "sources": sources,
        "settings": {
            "optimize": "gas",
            "outputSelection": {
                f"contracts/{contract_path.name}": ["evm.bytecode", "evm.deployedBytecode", "abi"]
            },
        },
    }


def _submit(api_key: str, address: str, contract_name: str,
            std_json: dict, constructor_args: str) -> str:
    """POST verifysourcecode; return GUID."""
    resp = requests.post(
        ETHERSCAN_API,
        params={"chainid": CHAIN_ID},
        data={
            "apikey":               api_key,
            "module":               "contract",
            "action":               "verifysourcecode",
            "contractaddress":      address,
            "sourceCode":           json.dumps(std_json),
            "codeformat":           "vyper-json",
            "contractname":         contract_name,
            "compilerversion":      COMPILER_VERSION,
            "optimizationUsed":     "1",
            "constructorArguements": constructor_args,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data.get("result", "")
    if data.get("status") != "1":
        if "Already Verified" in result:
            return "already_verified"
        raise RuntimeError(f"Etherscan submit failed: {result}")
    return result  # GUID


def _poll(api_key: str, guid: str, label: str) -> None:
    print(f"  Polling {label}...", end="", flush=True)
    for _ in range(60):
        time.sleep(5)
        resp = requests.get(
            ETHERSCAN_API,
            params={
                "chainid": CHAIN_ID,
                "apikey":  api_key,
                "module":  "contract",
                "action":  "checkverifystatus",
                "guid":    guid,
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


def main():
    load_dotenv()
    api_key    = os.environ["ETHERSCAN_API_KEY"]
    deployment = load_deployment()

    token_json  = _build_std_json(TOKEN_CONTRACT,  TOKEN_DEPS)
    faucet_json = _build_std_json(FAUCET_CONTRACT, [])

    constructor_args = deployment.get("constructor_args", {})

    contracts = [
        (deployment["llv2_usd"], "contracts/LLv2Token.vy:LLv2Token",    "LLv2Token (USD)",
         token_json,  constructor_args.get("llv2_usd", "")),
        (deployment["llv2_eth"], "contracts/LLv2Token.vy:LLv2Token",    "LLv2Token (ETH)",
         token_json,  constructor_args.get("llv2_eth", "")),
        (deployment["faucet"],   "contracts/LLv2Faucet.vy:LLv2Faucet", "LLv2Faucet",
         faucet_json, constructor_args.get("faucet", "")),
    ]

    for address, identifier, label, std_json, ctor_args in contracts:
        print(f"\nVerifying {label} at {address}...")
        try:
            guid = _submit(api_key, address, identifier, std_json, ctor_args)
            if guid == "already_verified":
                print("  Already verified")
            else:
                print(f"  GUID: {guid}")
                _poll(api_key, guid, label)
            print(f"  https://optimistic.etherscan.io/address/{address}#code")
        except RuntimeError as e:
            print(f"  FAILED: {e}")


if __name__ == "__main__":
    main()
