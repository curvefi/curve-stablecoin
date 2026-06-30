#!/usr/bin/env python3
"""Verify LendFactory, Configurator, and LeverageZap on Optimism Etherscan."""

import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from eth_abi import encode

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent.parent
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
    settings["outputSelection"] = {main_key: ["evm.bytecode", "evm.deployedBytecode", "abi"]}
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


def _call_address(rpc_url: str, to: str, sig: str) -> str:
    from eth_utils.crypto import keccak
    selector = keccak(sig.encode())[:4].hex()
    resp = requests.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": to, "data": "0x" + selector}, "latest"],
            "id": 1,
        },
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()["result"]
    return "0x" + result[2:].zfill(64)[-40:]


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
    api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not api_key:
        raise SystemExit("Missing ETHERSCAN_API_KEY")
    rpc_url = os.environ.get("OP_RPC_URL")
    if not rpc_url:
        raise SystemExit("Missing OP_RPC_URL")

    deployment_path = PROJECT_ROOT / "deployments" / "op" / "llamalend-op.jsonc"
    deployment = json.loads(deployment_path.read_text())

    factory_addr = deployment["factory"]
    configurator_addr = deployment["configurator"]
    leverage_zap_addr = deployment["leverage_zap"]
    deployer = deployment["deployer"]

    print("Fetching blueprint addresses from factory...")
    amm_bp = _call_address(rpc_url, factory_addr, "amm_blueprint()")
    ctrl_bp = _call_address(rpc_url, factory_addr, "controller_blueprint()")
    vault_bp = _call_address(rpc_url, factory_addr, "vault_blueprint()")
    ctrl_view_bp = _call_address(rpc_url, factory_addr, "controller_view_blueprint()")
    print(f"  AMM blueprint:             {amm_bp}")
    print(f"  Controller blueprint:      {ctrl_bp}")
    print(f"  Vault blueprint:           {vault_bp}")
    print(f"  ControllerView blueprint:  {ctrl_view_bp}")

    def vy_json(rel: str, optimize: str | None = None) -> dict:
        return _build_vyper_json(PROJECT_ROOT / rel, optimize=optimize)

    contracts = [
        (
            amm_bp,
            "AMM Blueprint (Vyper 0.4.3)",
            "curve_stablecoin/AMM.vy:AMM",
            vy_json("curve_stablecoin/AMM.vy", optimize="codesize"),
            "vyper:0.4.3",
            "vyper-json",
            "",
            "1",
        ),
        (
            ctrl_bp,
            "LendController Blueprint (Vyper 0.4.3)",
            "curve_stablecoin/lending/LendController.vy:LendController",
            vy_json("curve_stablecoin/lending/LendController.vy"),
            "vyper:0.4.3",
            "vyper-json",
            "",
            "1",
        ),
        (
            ctrl_view_bp,
            "LendControllerView Blueprint (Vyper 0.4.3)",
            "curve_stablecoin/lending/LendControllerView.vy:LendControllerView",
            vy_json("curve_stablecoin/lending/LendControllerView.vy", optimize="codesize"),
            "vyper:0.4.3",
            "vyper-json",
            "",
            "1",
        ),
        (
            vault_bp,
            "Vault Blueprint (Vyper 0.4.3)",
            "curve_stablecoin/lending/Vault.vy:Vault",
            vy_json("curve_stablecoin/lending/Vault.vy"),
            "vyper:0.4.3",
            "vyper-json",
            "",
            "1",
        ),
        (
            configurator_addr,
            "Configurator (Vyper 0.4.3)",
            "curve_stablecoin/Configurator.vy:Configurator",
            vy_json("curve_stablecoin/Configurator.vy"),
            "vyper:0.4.3",
            "vyper-json",
            encode(["address"], [deployer]).hex(),
            "1",
        ),
        (
            factory_addr,
            "LendFactory (Vyper 0.4.3)",
            "curve_stablecoin/lending/LendFactory.vy:LendFactory",
            vy_json("curve_stablecoin/lending/LendFactory.vy"),
            "vyper:0.4.3",
            "vyper-json",
            encode(
                ["address", "address", "address", "address", "address", "address", "address"],
                [amm_bp, ctrl_bp, vault_bp, ctrl_view_bp, configurator_addr, deployer, deployer],
            ).hex(),
            "1",
        ),
        (
            leverage_zap_addr,
            "LeverageZapLend (Vyper 0.4.3)",
            "curve_stablecoin/zaps/LeverageZapLend.vy:LeverageZapLend",
            vy_json("curve_stablecoin/zaps/LeverageZapLend.vy"),
            "vyper:0.4.3",
            "vyper-json",
            encode(["address"], [factory_addr]).hex(),
            "1",
        ),
    ]

    for (
        address,
        label,
        contract_name,
        std_json,
        compiler,
        codeformat,
        ctor_hex,
        opt_used,
    ) in contracts:
        print(f"\nVerifying {label} at {address}...")
        txhash = _get_creation_txhash(api_key, address)
        if txhash:
            print(f"  creation tx: {txhash}")
        try:
            guid = _submit(
                api_key,
                address,
                contract_name,
                std_json,
                ctor_hex,
                compiler,
                codeformat,
                opt_used,
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
