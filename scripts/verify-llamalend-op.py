#!/usr/bin/env python3
"""Verify all LlamaLend OP test market contracts on Optimism Etherscan."""

import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

import boa
import requests
from dotenv import load_dotenv
from eth_abi import encode
from eth_utils.crypto import keccak

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
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
    # Sort by descending depth so more-specific roots (snekmate, curve_std) are
    # checked before the broad PROJECT_ROOT, which is an ancestor of all paths.
    for root in sorted(PACKAGE_ROOTS.values(), key=lambda p: len(p.parts), reverse=True):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return path.name


def collect_sources(main_path: Path) -> dict[str, str]:
    """Recursively collect all Vyper source files reachable from main_path."""
    sources: dict[str, str] = {}
    visited: set[Path] = set()
    stack = [main_path]
    while stack:
        path = stack.pop()
        if path in visited:
            continue
        visited.add(path)
        content = path.read_text()
        sources[_source_key(path)] = content
        for m in IMPORT_RE.finditer(content):
            dep = _module_to_path(m.group(1), m.group(2))
            if dep and dep not in visited:
                stack.append(dep)
    return sources


# ---------------------------------------------------------------------------
# Standard JSON builders
# ---------------------------------------------------------------------------


def _build_vyper_json(main_path: Path) -> dict:
    sources = collect_sources(main_path)
    main_key = _source_key(main_path)
    return {
        "language": "Vyper",
        "sources": {k: {"content": v} for k, v in sources.items()},
        "settings": {
            # No "optimize" here — source-level # pragma optimize takes precedence,
            # and setting it here (e.g. "gas") conflicts with "# pragma optimize codesize"
            # causing Vyper to raise a settings conflict error.
            "evmVersion": "cancun",
            "outputSelection": {
                main_key: ["evm.bytecode", "evm.deployedBytecode", "abi"]
            },
        },
    }


def _build_solidity_json(sol_path: Path) -> dict:
    return {
        "language": "Solidity",
        "sources": {sol_path.name: {"content": sol_path.read_text()}},
        "settings": {
            "optimizer": {"enabled": False},
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode", "evm.deployedBytecode"]}},
        },
    }


# ---------------------------------------------------------------------------
# eth_call helpers
# ---------------------------------------------------------------------------


def _selector(sig: str) -> str:
    return keccak(sig.encode())[:4].hex()


def _eth_call(rpc_url: str, to: str, sig: str) -> str:
    resp = requests.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [{"to": to, "data": "0x" + _selector(sig)}, "latest"],
            "id": 1,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["result"]


def _call_address(rpc_url: str, to: str, sig: str) -> str:
    result = _eth_call(rpc_url, to, sig)
    return "0x" + result[2:].zfill(64)[-40:]


def _call_uint256(rpc_url: str, to: str, sig: str) -> int:
    return int(_eth_call(rpc_url, to, sig), 16)


# ---------------------------------------------------------------------------
# Debug helper — compares local compilation against on-chain bytecode
# ---------------------------------------------------------------------------


def _eth_get_code(rpc_url: str, address: str) -> bytes:
    resp = requests.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "method": "eth_getCode",
            "params": [address, "latest"],
            "id": 1,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return bytes.fromhex(resp.json()["result"][2:])


def _debug_contract(
    label: str,
    address: str,
    std_json: dict,
    compiler_version: str,
    codeformat: str,
    constructor_args_hex: str,
    rpc_url: str,
) -> None:
    """Compare locally compiled bytecode against on-chain; print diagnostics."""
    print(f"\n  [DEBUG] {label}")
    print(f"    sources: {list(std_json['sources'].keys())}")
    print(f"    settings: {std_json['settings']}")
    print(f"    compiler: {compiler_version}")
    print(f"    codeformat: {codeformat}")
    print(f"    constructor_args ({len(constructor_args_hex)//2} bytes): {constructor_args_hex[:80]}{'...' if len(constructor_args_hex) > 80 else ''}")

    onchain = _eth_get_code(rpc_url, address)
    print(f"    on-chain bytecode length: {len(onchain)} bytes")

    if codeformat != "vyper-json":
        print("    (skipping local compile — non-Vyper contract)")
        return

    from vyper.compiler import CompilerData
    from vyper.compiler.input_bundle import FilesystemInputBundle
    from vyper.compiler.settings import Settings

    settings = std_json.get("settings", {})
    evm_ver = settings.get("evmVersion")
    optimize = settings.get("optimize")

    main_key = next(k for k in std_json["sources"] if k.endswith(".vy") and not k.endswith(".vyi"))

    # FilesystemInputBundle searches all package roots for imports
    input_bundle = FilesystemInputBundle(list(PACKAGE_ROOTS.values()))

    try:
        file_input = input_bundle.load_file(main_key)
        cd = CompilerData(
            file_input,
            input_bundle=input_bundle,
            settings=Settings(evm_version=evm_ver, optimize=optimize),
        )
        local_runtime = bytes.fromhex(cd.bytecode_runtime.hex())
        print(f"    local compiled runtime length: {len(local_runtime)} bytes")

        if local_runtime == onchain:
            print("    ✓ BYTECODES MATCH — issue is constructor args or Etherscan settings")
        else:
            # Find first differing byte
            min_len = min(len(local_runtime), len(onchain))
            first_diff = next(
                (i for i in range(min_len) if local_runtime[i] != onchain[i]), min_len
            )
            print(f"    ✗ BYTECODES DIFFER at byte {first_diff} / {min_len}")
            print(f"      local[{first_diff}:{first_diff+8}]:   {local_runtime[first_diff:first_diff+8].hex()}")
            print(f"      onchain[{first_diff}:{first_diff+8}]: {onchain[first_diff:first_diff+8].hex()}")
            if len(local_runtime) != len(onchain):
                extra = len(onchain) - len(local_runtime)
                print(f"      length mismatch: local={len(local_runtime)}, onchain={len(onchain)} (+{extra} bytes)")
                if extra > 0 and extra % 32 == 0:
                    n_immutables = extra // 32
                    print(f"      on-chain has {n_immutables} extra 32-byte slots (immutable data section):")
                    tail = onchain[len(local_runtime):]
                    for i in range(n_immutables):
                        slot = tail[i*32:(i+1)*32]
                        print(f"        [{i:2d}] {slot.hex()}")

    except Exception as e:
        print(f"    local compile ERROR: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# AMM parameter computation via boa (uses snekmate exactly as the factory did)
# ---------------------------------------------------------------------------


def _compute_amm_params(A: int) -> tuple[int, int]:
    """Return (sqrt_band_ratio, log_A_ratio) using snekmate's exact algorithm."""
    A_ratio = 10**18 * A // (A - 1)
    src = f"""
# pragma version 0.4.3
from snekmate.utils import math

@external
def compute() -> (uint256, int256):
    A_ratio: uint256 = {A_ratio}
    return isqrt(A_ratio * 10**18), math._wad_ln(convert(A_ratio, int256))
"""
    contract = boa.loads(src)
    return contract.compute()


# ---------------------------------------------------------------------------
# Etherscan submit / poll (reused from verify_etherscan.py pattern)
# ---------------------------------------------------------------------------

ETHERSCAN_API = "https://api.etherscan.io/v2/api"
CHAIN_ID = "10"


def _get_creation_txhash(api_key: str, address: str) -> str | None:
    """Fetch the deployment transaction hash for a contract from Etherscan.

    Tries getcontractcreation first (works for directly deployed contracts),
    then falls back to txlistinternal (works for contracts created by other contracts,
    e.g. via create_from_blueprint).
    """
    # Method 1: getcontractcreation
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

    # Method 2: txlistinternal — finds the external tx that triggered the internal CREATE
    resp = requests.get(
        ETHERSCAN_API,
        params={
            "chainid": CHAIN_ID,
            "apikey": api_key,
            "module": "account",
            "action": "txlistinternal",
            "address": address,
            "startblock": "0",
            "endblock": "99999999",
            "sort": "asc",
            "page": "1",
            "offset": "10",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") == "1" and data.get("result"):
        for tx in data["result"]:
            if tx.get("type") == "create" or tx.get("to", "").lower() == address.lower():
                txhash = tx.get("hash")
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
        if "Already Verified" in result:
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
    load_dotenv()
    api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not api_key:
        raise SystemExit("Missing ETHERSCAN_API_KEY")
    rpc_url = os.environ.get("OP_RPC_URL")
    if not rpc_url:
        raise SystemExit("Missing OP_RPC_URL")

    deployment_path = PROJECT_ROOT / "deployments" / "llamalend-op-testing.jsonc"
    deployment = json.loads(deployment_path.read_text())
    params = deployment["params"]

    factory_addr = deployment["factory"]
    mp_addr = deployment["monetary_policy"]
    oracle_addr = deployment["price_oracle"]
    vault_addr = deployment["vault"]
    ctrl_addr = deployment["controller"]
    amm_addr = deployment["amm"]
    deployer = deployment["deployer"]

    # -- Fetch on-chain data --------------------------------------------------

    print("Fetching blueprint addresses from factory...")
    amm_bp = _call_address(rpc_url, factory_addr, "amm_blueprint()")
    ctrl_bp = _call_address(rpc_url, factory_addr, "controller_blueprint()")
    vault_bp = _call_address(rpc_url, factory_addr, "vault_blueprint()")
    ctrl_view_bp = _call_address(rpc_url, factory_addr, "controller_view_blueprint()")
    print(f"  AMM blueprint:             {amm_bp}")
    print(f"  Controller blueprint:      {ctrl_bp}")
    print(f"  Vault blueprint:           {vault_bp}")
    print(f"  ControllerView blueprint:  {ctrl_view_bp}")

    print("Fetching AMM base price...")
    base_price_scaled = _call_uint256(rpc_url, amm_addr, "get_base_price()")
    rate_mul = _call_uint256(rpc_url, amm_addr, "get_rate_mul()")
    if rate_mul == 10**18:
        # No interest accrued yet — get_base_price() == BASE_PRICE exactly
        base_price = base_price_scaled
    else:
        # get_base_price() = BASE_PRICE * rate_mul // 10**18 (Vyper integer division)
        # Reverse with ceiling to avoid off-by-one from truncation
        base_price = (base_price_scaled * 10**18 + rate_mul - 1) // rate_mul
        print(f"  WARNING: rate_mul={rate_mul} != 1e18, base_price may be off by 1 wei")
    print(f"  base_price: {base_price} (rate_mul={rate_mul})")

    print("Fetching token decimals...")
    borrowed_decimals = _call_uint256(rpc_url, params["borrowed_token"], "decimals()")
    collateral_decimals = _call_uint256(rpc_url, params["collateral_token"], "decimals()")
    borrowed_precision = 10 ** (18 - borrowed_decimals)
    collateral_precision = 10 ** (18 - collateral_decimals)

    print("Computing AMM sqrt/log params via snekmate...")
    sqrt_band_ratio, log_A_ratio = _compute_amm_params(params["A"])
    print(f"  sqrt_band_ratio: {sqrt_band_ratio}")
    print(f"  log_A_ratio:     {log_A_ratio}")

    # -- Build (address, label, std_json, compiler, codeformat, ctor_args) ---

    def vy_json(rel: str) -> dict:
        return _build_vyper_json(PROJECT_ROOT / rel)

    contracts = [
        # (address, label, contract_name, std_json, compiler, codeformat, ctor_hex, opt_used)
        # LendFactory first for faster iteration while debugging
        (
            factory_addr,
            "LendFactory (Vyper 0.4.3)",
            "curve_stablecoin/lending/LendFactory.vy:LendFactory",
            vy_json("curve_stablecoin/lending/LendFactory.vy"),
            "vyper:0.4.3",
            "vyper-json",
            encode(
                ["address", "address", "address", "address", "address", "address"],
                [amm_bp, ctrl_bp, vault_bp, ctrl_view_bp, deployer, deployer],
            ).hex(),
            "1",
        ),
        (
            vault_addr,
            "Vault (Vyper 0.4.3)",
            "curve_stablecoin/lending/Vault.vy:Vault",
            vy_json("curve_stablecoin/lending/Vault.vy"),
            "vyper:0.4.3",
            "vyper-json",
            "",  # no constructor args; vault is initialized via initialize()
            "1",
        ),
        (
            ctrl_addr,
            "LendController (Vyper 0.4.3)",
            "curve_stablecoin/lending/LendController.vy:LendController",
            vy_json("curve_stablecoin/lending/LendController.vy"),
            "vyper:0.4.3",
            "vyper-json",
            encode(
                ["address", "address", "address", "address", "address", "uint256", "uint256", "address"],
                [
                    vault_addr, amm_addr,
                    params["borrowed_token"], params["collateral_token"],
                    mp_addr,
                    params["loan_discount"], params["liquidation_discount"],
                    ctrl_view_bp,
                ],
            ).hex(),
            "1",
        ),
        (
            amm_addr,
            "AMM (Vyper 0.4.3)",
            "curve_stablecoin/AMM.vy:AMM",
            vy_json("curve_stablecoin/AMM.vy"),
            "vyper:0.4.3",
            "vyper-json",
            encode(
                [
                    "address", "uint256", "address", "uint256",
                    "uint256", "uint256", "int256",
                    "uint256", "uint256", "uint256", "address",
                ],
                [
                    params["borrowed_token"], borrowed_precision,
                    params["collateral_token"], collateral_precision,
                    params["A"], sqrt_band_ratio, log_A_ratio,
                    base_price, params["fee"], 0, oracle_addr,
                ],
            ).hex(),
            "1",
        ),
        (
            oracle_addr,
            "ChainlinkEMA (Solidity 0.8.25)",
            "ChainlinkEMA.sol:ChainlinkEMA",
            _build_solidity_json(PROJECT_ROOT / "scripts" / "solidity" / "ChainlinkEMA.sol"),
            "v0.8.25+commit.b61c2a91",
            "solidity-standard-json-input",
            encode(
                ["address", "uint256", "uint256"],
                [params["chainlink_feed"], params["observations"], params["interval"]],
            ).hex(),
            "0",
        ),
        (
            mp_addr,
            "SemilogMonetaryPolicy (Vyper 0.3.10)",
            "curve_stablecoin/mpolicies/SemilogMonetaryPolicy.vy:SemilogMonetaryPolicy",
            vy_json("curve_stablecoin/mpolicies/SemilogMonetaryPolicy.vy"),
            "vyper:0.3.10",
            "vyper-json",
            encode(
                ["address", "uint256", "uint256", "address"],
                [params["borrowed_token"], params["min_rate"], params["max_rate"], factory_addr],
            ).hex(),
            "1",
        ),
    ]

    # -- Submit and poll ------------------------------------------------------

    for (address, label, contract_name, std_json, compiler, codeformat, ctor_hex, opt_used) in contracts:
        print(f"\nVerifying {label} at {address}...")
        _debug_contract(label, address, std_json, compiler, codeformat, ctor_hex, rpc_url)
        txhash = _get_creation_txhash(api_key, address)
        if txhash:
            print(f"  creation tx: {txhash}")
        try:
            guid = _submit(
                api_key, address, contract_name, std_json,
                ctor_hex, compiler, codeformat, opt_used,
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


if __name__ == "__main__":
    main()
