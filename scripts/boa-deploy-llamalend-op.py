#!/usr/bin/env python3

import argparse
import json
import os
import time
from pathlib import Path

import boa
import boa_solidity
import requests
import solcx
from boa.network import NetworkEnv
from boa.rpc import EthereumRPC
from eth_account import Account


WETH = "0x4200000000000000000000000000000000000006"
WSTETH = "0x1F32b1c2345538c0c6f582fCB022739c4A194Ebb"
CHAINLINK_FEED = "0x524299Ab0987a7c4B3c8022a35669DdcdC715a10"

A = 70
FEE = 6 * 10**15
LOAN_DISCOUNT = 70000000000000008
LIQUIDATION_DISCOUNT = 40000000000000000
MIN_RATE = 31709791
MAX_RATE = 317097919837
SUPPLY_LIMIT = 2**256 - 1

OBSERVATIONS = 20
INTERVAL = 30


class RetryRPC(EthereumRPC):
    def fetch(self, method, params):
        delay = 1.0
        for attempt in range(6):
            try:
                return super().fetch(method, params)
            except requests.exceptions.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status != 503 or attempt == 5:
                    raise
                time.sleep(delay)
                delay *= 1.5


def _deploy(deployer: str, dry_run: bool, report_path: Path) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.add_account(Account.from_key(os.environ["PRIVATE_KEY"]), force_eoa=True)
        boa.env.suppress_debug_tt()

    amm_blueprint = boa.load_partial("curve_stablecoin/AMM.vy").deploy_as_blueprint()
    controller_blueprint = boa.load_partial(
        "curve_stablecoin/lending/LendController.vy"
    ).deploy_as_blueprint()
    vault_blueprint = boa.load_partial(
        "curve_stablecoin/lending/Vault.vy"
    ).deploy_as_blueprint()
    controller_view_blueprint = boa.load_partial(
        "curve_stablecoin/lending/LendControllerView.vy"
    ).deploy_as_blueprint()

    factory = boa.load_partial("curve_stablecoin/lending/LendFactory.vy").deploy(
        amm_blueprint.address,
        controller_blueprint.address,
        vault_blueprint.address,
        controller_view_blueprint.address,
        deployer,
        deployer,
    )

    monetary_policy = boa.load_partial(
        "curve_stablecoin/mpolicies/SemilogMonetaryPolicy.vy"
    ).deploy(WETH, MIN_RATE, MAX_RATE, factory.address)

    solcx.install_solc("0.8.25")
    solcx.set_solc_version("0.8.25")
    oracle = boa.load_partial_solc("scripts/solidity/ChainlinkEMA.sol").deploy(
        CHAINLINK_FEED,
        OBSERVATIONS,
        INTERVAL,
    )

    deployed = factory.create(
        WETH,
        WSTETH,
        A,
        FEE,
        LOAN_DISCOUNT,
        LIQUIDATION_DISCOUNT,
        oracle.address,
        monetary_policy.address,
        "wstETH/WETH",
        SUPPLY_LIMIT,
        sender=deployer,
    )

    report = {
        "chain_id": boa.env.get_chain_id(),
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "factory": factory.address,
        "monetary_policy": monetary_policy.address,
        "price_oracle": oracle.address,
        "vault": deployed[0],
        "controller": deployed[1],
        "amm": deployed[2],
        "params": {
            "borrowed_token": WETH,
            "collateral_token": WSTETH,
            "chainlink_feed": CHAINLINK_FEED,
            "A": A,
            "fee": FEE,
            "loan_discount": LOAN_DISCOUNT,
            "liquidation_discount": LIQUIDATION_DISCOUNT,
            "min_rate": MIN_RATE,
            "max_rate": MAX_RATE,
            "supply_limit": SUPPLY_LIMIT,
            "observations": OBSERVATIONS,
            "interval": INTERVAL,
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("Factory:", factory.address)
    print("Monetary Policy:", monetary_policy.address)
    print("Price Oracle:", oracle.address)
    print("Vault:", deployed[0])
    print("Controller:", deployed[1])
    print("AMM:", deployed[2])
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy LlamaLend on OP")
    parser.add_argument("--rpc-url", default=os.environ.get("OP_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend-op-testing.jsonc",
        help="Where to write the deployment report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or OP_RPC_URL")

    private_key = os.environ.get("PRIVATE_KEY")
    if not private_key:
        raise SystemExit("Missing PRIVATE_KEY")

    deployer = Account.from_key(private_key).address

    report_path = Path(args.report_path)

    if args.dry_run:
        with boa.fork(args.rpc_url):
            _deploy(deployer, dry_run=True, report_path=report_path)
    else:
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            _deploy(deployer, dry_run=False, report_path=report_path)


if __name__ == "__main__":
    main()
