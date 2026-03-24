#!/usr/bin/env python3
"""
Generate an HTML overview from a LlamaLend deployment JSONC file.
Checks Etherscan (OP) to flag which contracts are verified.

Usage:
    python scripts/gen-deployment-html.py deployments/llamalend-op-testing.jsonc
    python scripts/gen-deployment-html.py deployments/llamalend-op-testing.jsonc --output deployments/llamalend-op-testing.html
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

EXPLORERS = {
    1:   "https://etherscan.io",
    10:  "https://optimistic.etherscan.io",
    137: "https://polygonscan.com",
    42161: "https://arbiscan.io",
}

ETHERSCAN_API_V2 = "https://api.etherscan.io/v2/api"


def is_verified(chain_id: int, address: str, api_key: str | None) -> bool:
    params = {
        "chainid": chain_id,
        "module": "contract",
        "action": "getsourcecode",
        "address": address,
    }
    if api_key:
        params["apikey"] = api_key
    try:
        r = requests.get(ETHERSCAN_API_V2, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "1" and data.get("result"):
            source = data["result"][0].get("SourceCode", "")
            return bool(source)
    except Exception:
        pass
    return False


def addr_link(explorer: str, address: str, verified: bool | None = None) -> str:
    href = f"{explorer}/address/{address}"
    link = f'<a href="{href}" class="link" target="_blank">{address}</a>'
    if verified is True:
        link += ' <span class="verified">✓ verified</span>'
    elif verified is False:
        link += ' <span class="unverified">✗ not verified</span>'
    return link


def field(label: str, value: str) -> str:
    return f"""            <div class="field">
                <div class="label">{label}:</div>
                <div class="value">{value}</div>
            </div>"""


def render(data: dict, explorer: str, title: str, contracts_verified: dict) -> str:
    ts = data.get("timestamp", 0)
    ts_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    p = data.get("params", {})

    # Contract rows — only include keys that exist in the JSON
    contract_keys = ["factory", "monetary_policy", "price_oracle", "leverage_zap", "vault", "controller", "amm"]
    contract_labels = {
        "factory": "Factory",
        "monetary_policy": "Monetary Policy",
        "price_oracle": "Price Oracle",
        "leverage_zap": "Leverage Zap",
        "vault": "Vault",
        "controller": "Controller",
        "amm": "AMM",
    }
    contract_rows = []
    for key in contract_keys:
        if key in data:
            addr = data[key]
            verified = contracts_verified.get(addr)
            contract_rows.append(field(contract_labels[key], addr_link(explorer, addr, verified)))

    # Param rows
    param_labels = {
        "borrowed_token": "Borrowed Token",
        "collateral_token": "Collateral Token",
        "chainlink_feed": "Chainlink Feed",
        "A": "A",
        "fee": "Fee",
        "loan_discount": "Loan Discount",
        "liquidation_discount": "Liquidation Discount",
        "min_rate": "Min Rate",
        "max_rate": "Max Rate",
        "supply_limit": "Supply Limit",
        "observations": "Observations",
        "interval": "Interval",
    }
    addr_params = {"borrowed_token", "collateral_token", "chainlink_feed"}
    param_rows = []
    for key, label in param_labels.items():
        if key not in p:
            continue
        val = p[key]
        if key in addr_params:
            cell = addr_link(explorer, val)
        else:
            cell = f'<span class="raw-value">{val}</span>'
        param_rows.append(field(label, cell))

    contracts_section = "\n".join(contract_rows)
    params_section = "\n".join(param_rows)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}
        h1 {{
            color: #333;
            text-align: center;
        }}
        .section {{
            background-color: #f9f9f9;
            padding: 15px;
            margin: 15px 0;
            border-radius: 5px;
            border-left: 4px solid #007bff;
        }}
        .section h2 {{
            margin-top: 0;
            color: #007bff;
        }}
        .field {{
            display: flex;
            margin: 10px 0;
        }}
        .label {{
            font-weight: bold;
            width: 180px;
        }}
        .value {{
            flex: 1;
        }}
        .link {{
            color: #0066cc;
            text-decoration: none;
            word-break: break-all;
        }}
        .link:hover {{
            text-decoration: underline;
        }}
        .raw-value {{
            background-color: #eee;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: monospace;
        }}
        .verified {{
            color: #2a7a2a;
            font-weight: bold;
        }}
        .unverified {{
            color: #b00;
            font-weight: bold;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>

        <div class="section">
            <h2>Deployment Info</h2>
{field("Chain ID", str(data.get("chain_id", "")))}
{field("Deployer", addr_link(explorer, data["deployer"]))}
{field("Dry Run", str(data.get("dry_run", "")).lower())}
{field("Timestamp", f'<span class="raw-value">{ts}</span> ({ts_str})')}
        </div>

        <div class="section">
            <h2>Contracts</h2>
{contracts_section}
        </div>

        <div class="section">
            <h2>Parameters</h2>
{params_section}
        </div>
    </div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HTML overview from deployment JSONC")
    parser.add_argument("input", help="Path to deployment .jsonc file")
    parser.add_argument("--output", help="Output HTML path (default: same name as input with .html)")
    parser.add_argument("--title", help="Page title (default: derived from filename)")
    parser.add_argument("--no-verify-check", action="store_true", help="Skip Etherscan verification check")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"File not found: {input_path}")

    output_path = Path(args.output) if args.output else input_path.with_suffix(".html")
    title = args.title or input_path.stem.replace("-", " ").replace("_", " ").title()

    data = json.loads(input_path.read_text())
    chain_id = data.get("chain_id", 10)
    explorer = EXPLORERS.get(chain_id, f"https://etherscan.io")

    # Collect all contract addresses to check
    contract_keys = ["factory", "monetary_policy", "price_oracle", "leverage_zap", "vault", "controller", "amm"]
    contracts = {data[k] for k in contract_keys if k in data}

    api_key = os.environ.get("ETHERSCAN_API_KEY")

    contracts_verified: dict[str, bool | None] = {}
    if args.no_verify_check:
        contracts_verified = {addr: None for addr in contracts}
    else:
        if not api_key:
            print("Warning: ETHERSCAN_API_KEY not set, verification check may fail")
        print(f"Checking verification status for {len(contracts)} contracts on chain {chain_id}...")
        for addr in contracts:
            v = is_verified(chain_id, addr, api_key)
            contracts_verified[addr] = v
            status = "verified ✓" if v else "not verified ✗"
            print(f"  {addr}  {status}")

    html = render(data, explorer, title, contracts_verified)
    output_path.write_text(html)
    print(f"Written: {output_path}")


if __name__ == "__main__":
    main()
