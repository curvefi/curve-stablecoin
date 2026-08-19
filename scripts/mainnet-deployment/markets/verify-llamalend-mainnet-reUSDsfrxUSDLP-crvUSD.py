#!/usr/bin/env python3
"""Verify the reUSD/sfrxUSD LP/crvUSD market's oracle stack and monetary policy
on Etherscan (Mainnet).

Reads the deployment report written by
    deploy-llamalend-mainnet-reUSDsfrxUSDLP-crvUSD.py
and submits source + constructor args for each contract that script deploys
directly:
    1. StableSwapNGLPOracle (lp_oracle)      -- ctor: (lp_pool, coin_idx, ema_time)
    2. CurvePoolOracle      (bridge_oracle)  -- ctor: (bridge_pool, base_idx, quote_idx)
    3. ChainOracle          (price_oracle)   -- ctor: ([lp_oracle, bridge_oracle, agg])
    4. HyperbolicMP         (monetary_policy)-- ctor: (controller, target_util,
                                                target_rate, low, high, rate_shift)

Deliberately not submitted - everything deployed from a blueprint, whose
implementation is verified once, elsewhere:
  * vault / controller / amm - blueprint copies from the lending factory, covered
    by verify-llamalend-mainnet-factory.py;
  * lm_callback - blueprint copy from the LM callback factory, covered by
    verify-lm-callback-factory.py;
  * gauge - from the DAO's gauge factory, whose implementation lives outside
    this repo.

Run:
    ETHERSCAN_API_KEY=... python scripts/mainnet-deployment/markets/\
verify-llamalend-mainnet-reUSDsfrxUSDLP-crvUSD.py
"""

import argparse
import importlib.util
import json
import os
import re
import time
from pathlib import Path, PurePath

import requests
from eth_abi import encode

# ---------------------------------------------------------------------------
# Contract sources (must match deploy-llamalend-mainnet-reUSDsfrxUSDLP-crvUSD.py)
# ---------------------------------------------------------------------------

STABLESWAP_NG_LP_ORACLE_SRC = (
    "curve_stablecoin/price_oracles/v2/StableSwapNGLPOracle.vy"
)
CURVE_POOL_ORACLE_SRC = "curve_stablecoin/price_oracles/v2/CurvePoolOracle.vy"
CHAIN_ORACLE_SRC = "curve_stablecoin/price_oracles/v2/ChainOracle.vy"
HYPERBOLIC_MP_SRC = "curve_stablecoin/mpolicies/v2/HyperbolicMP.vy"

DEFAULT_DEPLOYMENT = (
    "deployments/mainnet/markets/llamalend-mainnet-reUSDsfrxUSDLP-crvUSD.jsonc"
)

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
# StableSwapNGLPOracle builds on `stableswap_ng.LPOracle`, which ships as an
# installed (namespace) package rather than living in this repo.
STABLESWAP_NG_ROOT = Path(
    importlib.util.find_spec("stableswap_ng").submodule_search_locations[0]
).parent

PACKAGE_ROOTS = {
    "curve_stablecoin": PROJECT_ROOT,
    "curve_std": CURVE_STD_ROOT,
    "snekmate": SNEKMATE_ROOT,
    "stableswap_ng": STABLESWAP_NG_ROOT,
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
# Namespace de-collision
# ---------------------------------------------------------------------------


def _decollide(sources: dict[str, str]) -> dict[str, str]:
    """Make every source's filename stem unique for Vyper's standard-JSON input.

    Vyper's `vyper-json` keys contract uniqueness on the *basename stem*, so two
    files sharing a name (e.g. `curve_stablecoin/constants.vy` and
    `curve_std/constants.vy`, both pulled in by ERC4626EMAWrapper via the `ema`
    module) raise "Contract namespace collision" and the compile aborts - which
    Etherscan reports as "Unable to locate a matching contract".

    Rename all-but-one file of each colliding group to a unique stem and rewrite
    the `from <pkg> import <name>` statements that reference them, aliasing back
    to the original bound name.  Renaming a module file and aliasing its import
    does not change Vyper's compiled bytecode, so the result still matches the
    on-chain code.  The main contract's stem is unique, so it is never renamed.
    """
    groups: dict[str, list[str]] = {}
    for key in sources:
        groups.setdefault(PurePath(key).stem, []).append(key)

    out = dict(sources)
    renames: list[tuple[str, str, str]] = []  # (dotted_pkg, old_name, new_name)
    for stem, keys in groups.items():
        if len(keys) < 2:
            continue
        for key in sorted(keys)[1:]:
            p = PurePath(key)
            parts = p.parent.parts
            new_name = f"{parts[0]}_{stem}" if parts else f"x_{stem}"
            out[str(p.with_name(new_name + p.suffix))] = out.pop(key)
            renames.append((".".join(parts), stem, new_name))

    for dotted, old_name, new_name in renames:
        # from <dotted> import <old>[ as <alias>] -> from <dotted> import <new> as <bound>
        pat = re.compile(
            rf"^(from\s+{re.escape(dotted)}\s+import\s+){re.escape(old_name)}"
            r"(\s+as\s+\w+)?\s*$",
            re.MULTILINE,
        )

        def repl(m: re.Match) -> str:
            bound = m.group(2).strip()[3:].strip() if m.group(2) else old_name
            return f"{m.group(1)}{new_name} as {bound}"

        for key in list(out):
            out[key] = pat.sub(repl, out[key])
    return out


# ---------------------------------------------------------------------------
# Standard JSON builder
# ---------------------------------------------------------------------------


def _build_vyper_json(main_path: Path, optimize: str | None = None) -> dict:
    sources = _decollide(collect_sources(main_path))
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
CHAIN_ID = "1"


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
        description="Verify reUSD/sfrxUSD LP/crvUSD market contracts on Etherscan"
    )
    parser.add_argument(
        "--deployment",
        default=DEFAULT_DEPLOYMENT,
        help="Path to the market deployment report",
    )
    args = parser.parse_args()

    api_key = os.environ.get("ETHERSCAN_API_KEY")
    if not api_key:
        raise SystemExit("Missing ETHERSCAN_API_KEY")

    deployment_path = Path(args.deployment)
    if not deployment_path.is_absolute():
        deployment_path = PROJECT_ROOT / deployment_path
    if not deployment_path.exists():
        raise SystemExit(f"Deployment report not found: {deployment_path}")
    deployment = json.loads(deployment_path.read_text())
    if deployment.get("dry_run"):
        raise SystemExit(f"{deployment_path} is a dry-run report (fork addresses)")
    params = deployment["params"]

    lp_oracle_addr = deployment["lp_oracle"]
    bridge_oracle_addr = deployment["bridge_oracle"]
    oracle_addr = deployment["price_oracle"]
    monetary_policy_addr = deployment["monetary_policy"]
    controller_addr = deployment["controller"]

    lp_pool = params["lp_pool"]
    lp_coin_idx = params["lp_coin_idx"]
    bridge_pool = params["bridge_pool"]
    bridge_base_idx = params["bridge_base_idx"]
    bridge_quote_idx = params["bridge_quote_idx"]
    agg = params["agg"]
    ema_time = params["ema_time"]
    target_utilization = params["target_utilization"]
    target_rate = params["target_rate"]
    low_ratio = params["low_ratio"]
    high_ratio = params["high_ratio"]
    rate_shift = params["rate_shift"]

    def vy_json(rel: str, optimize: str | None = None) -> dict:
        return _build_vyper_json(PROJECT_ROOT / rel, optimize=optimize)

    contracts = [
        (
            lp_oracle_addr,
            "StableSwapNGLPOracle (Vyper 0.4.3)",
            f"{STABLESWAP_NG_LP_ORACLE_SRC}:StableSwapNGLPOracle",
            vy_json(STABLESWAP_NG_LP_ORACLE_SRC),
            "vyper:0.4.3",
            "vyper-json",
            encode(
                ["address", "uint256", "uint256"],
                [lp_pool, lp_coin_idx, ema_time],
            ).hex(),
            "1",
        ),
        (
            bridge_oracle_addr,
            "CurvePoolOracle (Vyper 0.4.3)",
            f"{CURVE_POOL_ORACLE_SRC}:CurvePoolOracle",
            vy_json(CURVE_POOL_ORACLE_SRC),
            "vyper:0.4.3",
            "vyper-json",
            encode(
                ["address", "uint256", "uint256"],
                [bridge_pool, bridge_base_idx, bridge_quote_idx],
            ).hex(),
            "1",
        ),
        (
            oracle_addr,
            "ChainOracle (Vyper 0.4.3)",
            f"{CHAIN_ORACLE_SRC}:ChainOracle",
            vy_json(CHAIN_ORACLE_SRC),
            "vyper:0.4.3",
            "vyper-json",
            # The chain is ordered: LP/reUSD, reUSD/crvUSD, crvUSD/USD.
            encode(["address[]"], [[lp_oracle_addr, bridge_oracle_addr, agg]]).hex(),
            "1",
        ),
        (
            monetary_policy_addr,
            "HyperbolicMP (Vyper 0.4.3)",
            f"{HYPERBOLIC_MP_SRC}:HyperbolicMP",
            vy_json(HYPERBOLIC_MP_SRC),
            "vyper:0.4.3",
            "vyper-json",
            encode(
                ["address", "uint256", "uint256", "uint256", "uint256", "uint256"],
                [
                    controller_addr,
                    target_utilization,
                    target_rate,
                    low_ratio,
                    high_ratio,
                    rate_shift,
                ],
            ).hex(),
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
            print(f"  https://etherscan.io/address/{address}#code")
        except RuntimeError as e:
            print(f"  FAILED: {e}")
            print(f"  UNVERIFIED: {label} at {address}")


if __name__ == "__main__":
    main()
