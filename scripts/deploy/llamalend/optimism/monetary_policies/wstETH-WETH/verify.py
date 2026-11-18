#!/usr/bin/env python3
"""Verify the wstETH/WETH WstETHRateCalculator and HyperbolicDynamicMP on Optimism Etherscan.

Companion to deploy.py: reads the addresses, the controller and the parameters from
the report it writes (deployments/llamalend/optimism/monetary_policies/wstETH-WETH.jsonc).

Run:
    ETHERSCAN_API_KEY=... python scripts/deploy/llamalend/optimism/monetary_policies/\
wstETH-WETH/verify.py
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
# Contract sources
# ---------------------------------------------------------------------------

RATE_CALCULATOR_SRC = (
    "curve_stablecoin/mpolicies/v2/rate_calculators/WstETHRateCalculator.vy"
)
RATE_CALCULATOR_NAME = f"{RATE_CALCULATOR_SRC}:WstETHRateCalculator"
HYPERBOLIC_DYNAMIC_MP_SRC = "curve_stablecoin/mpolicies/v2/HyperbolicDynamicMP.vy"
HYPERBOLIC_DYNAMIC_MP_NAME = f"{HYPERBOLIC_DYNAMIC_MP_SRC}:HyperbolicDynamicMP"

DEFAULT_REPORT = "deployments/llamalend/optimism/monetary_policies/wstETH-WETH.jsonc"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[6]
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify wstETH/WETH WstETHRateCalculator + HyperbolicDynamicMP on Optimism Etherscan"
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
    params = report["params"]

    contracts = [
        (
            report["rate_calculator"],
            "WstETHRateCalculator (Vyper 0.4.3)",
            RATE_CALCULATOR_NAME,
            RATE_CALCULATOR_SRC,
            encode(
                ["address", "uint256"],
                [params["wsteth_rate_oracle"], params["avg_window"]],
            ).hex(),
        ),
        (
            report["monetary_policy"],
            "HyperbolicDynamicMP (Vyper 0.4.3)",
            HYPERBOLIC_DYNAMIC_MP_NAME,
            HYPERBOLIC_DYNAMIC_MP_SRC,
            encode(
                ["address", "address", "uint256", "uint256", "uint256", "uint256"],
                [
                    report["controller"],
                    report["rate_calculator"],
                    params["target_utilization"],
                    params["low_ratio"],
                    params["high_ratio"],
                    params["rate_shift"],
                ],
            ).hex(),
        ),
    ]

    for address, label, contract_name, source, ctor_hex in contracts:
        print(f"\nVerifying {label} at {address}...")
        txhash = _get_creation_txhash(api_key, address)
        if txhash:
            print(f"  creation tx: {txhash}")
        try:
            guid = _submit(
                api_key,
                address,
                contract_name,
                _build_vyper_json(PROJECT_ROOT / source),
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
