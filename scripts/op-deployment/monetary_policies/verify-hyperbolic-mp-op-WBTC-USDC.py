#!/usr/bin/env python3
"""Verify the WBTC/USDC HyperbolicMP monetary policy on Optimism Etherscan.

Companion to boa-deploy-hyperbolic-mp-op-WBTC-USDC.py, which deploys just the
policy against the existing market and writes no report. Update the market
deployment file's `monetary_policy` field to the redeployed HyperbolicMP address,
then run this; the controller (a HyperbolicMP constructor arg) is read from that
same file, and the curve parameters are the constants the deploy script uses.

Run:
    ETHERSCAN_API_KEY=... python scripts/op-deployment/monetary_policies/\
verify-hyperbolic-mp-op-WBTC-USDC.py
"""

import argparse
import importlib.util
import json
import os
import re
import time
from pathlib import Path

import requests
from eth_abi import encode

# ---------------------------------------------------------------------------
# Contract source + curve params (must match boa-deploy-hyperbolic-mp-op-WBTC-USDC.py)
# ---------------------------------------------------------------------------

HYPERBOLIC_MP_SRC = "curve_stablecoin/mpolicies/v2/HyperbolicMP.vy"
HYPERBOLIC_MP_NAME = f"{HYPERBOLIC_MP_SRC}:HyperbolicMP"

TARGET_UTILIZATION = 85 * 10**16  # 85%
TARGET_RATE = 5 * 10**16 // (365 * 86400)  # ~5% APR (per second, 1e18-scaled)
LOW_RATIO = 10**17  # 0.1x base at 0% utilization
HIGH_RATIO = 60 * 10**18  # 60x base at 100% utilization
RATE_SHIFT = 0  # no flat shift

DEFAULT_DEPLOYMENT = "deployments/op/llamalend-op-WBTC-USDC.jsonc"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SNEKMATE_ROOT = Path(
    importlib.util.find_spec("snekmate").submodule_search_locations[0]
).parent
CURVE_STD_ROOT = Path(
    importlib.util.find_spec("curve_std").submodule_search_locations[0]
).parent

PACKAGE_ROOTS = {
    "curve_stablecoin": PROJECT_ROOT,
    "curve_std": CURVE_STD_ROOT,
    "snekmate": SNEKMATE_ROOT,
}

BUILTIN_PACKAGES = {"vyper"}

# ---------------------------------------------------------------------------
# Vyper source collector (recursive import resolver)
# ---------------------------------------------------------------------------

IMPORT_RE = re.compile(r"^from\s+([\w.]+)\s+import\s+(\w+)", re.MULTILINE)


def _module_to_path(pkg: str, name: str) -> Path | None:
    top = pkg.split(".")[0]
    if top in BUILTIN_PACKAGES:
        return None
    if top not in PACKAGE_ROOTS:
        return None
    root = PACKAGE_ROOTS[top]
    parts = [top] + pkg.split(".")[1:] + [name]
    rel = Path(*parts)
    for ext in (".vy", ".vyi"):
        p = root / rel.with_suffix(ext)
        if p.exists():
            return p
    return None


def _source_key(path: Path) -> str:
    for root in sorted(
        PACKAGE_ROOTS.values(), key=lambda p: len(p.parts), reverse=True
    ):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return path.name


def collect_sources(main_path: Path) -> dict[str, str]:
    sources: dict[str, str] = {}
    visited: set[Path] = set()
    stack = [main_path]
    while stack:
        path = stack.pop()
        if path in visited:
            continue
        visited.add(path)
        content = path.read_text()
        key = _source_key(path)
        sources[key] = content
        for m in IMPORT_RE.finditer(content):
            dep = _module_to_path(m.group(1), m.group(2))
            if dep and dep not in visited:
                stack.append(dep)
    return sources


# ---------------------------------------------------------------------------
# Standard JSON builder
# ---------------------------------------------------------------------------


def _build_vyper_json(main_path: Path, optimize: str | None = None) -> dict:
    sources = collect_sources(main_path)
    main_key = _source_key(main_path)
    if optimize:
        pragma_line = f"# pragma optimize {optimize}\n"
        if pragma_line in sources.get(main_key, ""):
            sources[main_key] = sources[main_key].replace(pragma_line, "")
    settings: dict = {"evmVersion": "cancun"}
    if optimize:
        settings["optimize"] = optimize
    settings["outputSelection"] = {
        main_key: ["evm.bytecode", "evm.deployedBytecode", "abi"]
    }
    return {
        "language": "Vyper",
        "sources": {k: {"content": v} for k, v in sources.items()},
        "settings": settings,
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
        description="Verify WBTC/USDC HyperbolicMP on Optimism Etherscan"
    )
    parser.add_argument(
        "--deployment",
        default=DEFAULT_DEPLOYMENT,
        help="Path to the market deployment file (update its monetary_policy field "
        "to the redeployed HyperbolicMP address first)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not api_key:
        raise SystemExit("Missing ETHERSCAN_API_KEY")

    deployment_path = Path(args.deployment)
    if not deployment_path.is_absolute():
        deployment_path = PROJECT_ROOT / deployment_path
    if not deployment_path.exists():
        raise SystemExit(f"Deployment file not found: {deployment_path}")
    deployment = json.loads(deployment_path.read_text())
    contracts_map = deployment.get("contracts", deployment)

    monetary_policy_addr = contracts_map["monetary_policy"]
    controller_addr = contracts_map["controller"]

    std_json = _build_vyper_json(PROJECT_ROOT / HYPERBOLIC_MP_SRC)
    ctor_hex = encode(
        ["address", "uint256", "uint256", "uint256", "uint256", "uint256"],
        [
            controller_addr,
            TARGET_UTILIZATION,
            TARGET_RATE,
            LOW_RATIO,
            HIGH_RATIO,
            RATE_SHIFT,
        ],
    ).hex()

    label = "HyperbolicMP (Vyper 0.4.3)"
    address = monetary_policy_addr
    print(f"Verifying {label} at {address}...")
    print(f"  controller: {controller_addr}")
    txhash = _get_creation_txhash(api_key, address)
    if txhash:
        print(f"  creation tx: {txhash}")
    try:
        guid = _submit(
            api_key,
            address,
            HYPERBOLIC_MP_NAME,
            std_json,
            ctor_hex,
            "vyper:0.4.3",
            "vyper-json",
            "1",
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
