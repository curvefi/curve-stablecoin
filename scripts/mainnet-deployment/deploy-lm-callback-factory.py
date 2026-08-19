#!/usr/bin/env python3
"""
Deploy the LM Callback stack (blueprint + factory) on Ethereum Mainnet.

Mainnet only: `LMCallback` hardcodes CRV, the GaugeController and the Minter,
so the factory it is deployed from has no meaning on any other chain.

This deploys, in order:
    1. LMCallback blueprint (ERC-5202, 3-byte preamble - matches the
       `code_offset=3` the factory passes to `create_from_blueprint`)
    2. LMCallbackFactory(owner, blueprint)

The factory is deployed unpaused and owned by the Ownership DAO, which is the
only account that can rotate the blueprint or pause deployments afterwards.
Deploying a callback itself is permissionless, so nothing else is needed here.

Attaching a deployed callback to a market is a separate governance action (the
DAO owns the factory/controller), e.g. via `Configurator.set_callback(...)`.

Under --dry-run the blueprint is smoke-tested end to end: a callback is deployed
through the factory against a live AMM (read from an existing market deployment
report, or --smoke-amm) and its immutables are read back. This exercises the
blueprint preamble/code offset and the callback constructor, which reaches out
to the AMM and to CRV. It only ever runs on the fork.

Run:
    # dry-run against a fork
    MAINNET_RPC_URL=... python scripts/mainnet-deployment/\
deploy-lm-callback-factory.py --dry-run --account-name <name>

    # broadcast
    MAINNET_RPC_URL=... python scripts/mainnet-deployment/\
deploy-lm-callback-factory.py --account-name <name>
"""

import argparse
import json
import os
import time
from getpass import getpass
from pathlib import Path

import boa
import requests
from boa.network import NetworkEnv
from boa.rpc import EthereumRPC
from eth_account import account
from eth_utils import to_checksum_address


CHAIN_ID = 1
MAINNET_DAO = "0x40907540d8a6C65c637785e8f8B742ae6b0b9968"  # Ownership DAO

# --- Contract sources ---
LM_CALLBACK = "curve_stablecoin/lm_callback/LMCallback.vy"
LM_CALLBACK_FACTORY = "curve_stablecoin/lm_callback/LMCallbackFactory.vy"


def _load_account(fname: str) -> account.LocalAccount:
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


class RetryRPC(EthereumRPC):
    def fetch(self, method, params):
        delay = 1.0
        for attempt in range(6):
            try:
                result = super().fetch(method, params)
                if result is None and method == "eth_getBlockByNumber" and attempt < 5:
                    time.sleep(delay)
                    delay *= 1.5
                    continue
                return result
            except requests.exceptions.HTTPError as exc:
                status = getattr(exc.response, "status_code", None)
                if status != 503 or attempt == 5:
                    raise
                time.sleep(delay)
                delay *= 1.5


def _smoke_test(factory, amm: str) -> None:
    """Deploy a callback for `amm` through the factory and read it back."""
    lm_callback_addr = factory.deploy_lm_callback(amm)
    lm_callback = boa.load_partial(LM_CALLBACK).at(lm_callback_addr)

    assert factory.is_valid_lm_callback(lm_callback_addr), "callback not registered"
    assert factory.get_lm_callback_count() == 1
    assert factory.get_lm_callback(0) == lm_callback_addr
    assert to_checksum_address(lm_callback.AMM()) == to_checksum_address(amm)
    # Not the AMM's configured callback yet, so it must not consider itself live.
    assert not lm_callback.attached()

    print("Smoke test (fork only):")
    print("  AMM:", amm)
    print("  LM Callback:", lm_callback_addr)
    print("  collateral token:", lm_callback.COLLATERAL_TOKEN())


def _deploy(
    deployer: str,
    dry_run: bool,
    owner: str,
    report_path: Path,
    smoke_amm: str | None,
) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    lm_callback_blueprint = boa.load_partial(LM_CALLBACK).deploy_as_blueprint()

    factory = boa.load_partial(LM_CALLBACK_FACTORY).deploy(
        owner,
        lm_callback_blueprint.address,
    )

    # The factory reverts on a zero owner/blueprint, so these only guard against
    # deploying with arguments in the wrong order.
    assert to_checksum_address(factory.owner()) == to_checksum_address(owner)
    assert to_checksum_address(factory.lm_callback_blueprint()) == to_checksum_address(
        lm_callback_blueprint.address
    )
    assert not factory.paused()
    assert factory.get_lm_callback_count() == 0

    if dry_run and smoke_amm is not None:
        _smoke_test(factory, smoke_amm)

    chain_id = CHAIN_ID
    if hasattr(boa.env, "get_chain_id"):
        chain_id = boa.env.get_chain_id()

    contracts = {
        "lm_callback_blueprint": lm_callback_blueprint.address,
        "lm_callback_factory": factory.address,
    }

    report = {
        "chain_id": chain_id,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "contracts": contracts,
        "params": {
            "owner": to_checksum_address(owner),
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("Deployed contracts:")
    for name, address in contracts.items():
        print(f"  {name}: {address}")
    print("Owner:", to_checksum_address(owner))
    print("Report:", report_path)
    print()
    print(
        "Next step (per market, governance): Configurator.set_callback(controller, "
        "lm_callback) for a callback deployed via "
        f"{factory.address}.deploy_lm_callback(amm)"
    )


def _resolve_smoke_amm(smoke_amm: str | None) -> str | None:
    """AMM used by the fork-only smoke test; without one the test is skipped."""
    if not smoke_amm:
        print("No --smoke-amm: skipping the blueprint smoke test")
        return None
    return to_checksum_address(smoke_amm)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy the LMCallback blueprint + LMCallbackFactory on Mainnet"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("MAINNET_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--account-name",
        default=os.environ.get("ACCOUNT_NAME"),
        help="Brownie account name",
    )
    parser.add_argument(
        "--owner",
        default=MAINNET_DAO,
        help="Factory owner, allowed to rotate the blueprint and pause (default: DAO)",
    )
    parser.add_argument(
        "--smoke-amm",
        help="AMM to smoke-test the blueprint against (dry-run only)",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/mainnet/lm-callback-factory.jsonc",
        help="Where to write the deployment report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or MAINNET_RPC_URL")
    if not args.account_name:
        raise SystemExit("Missing --account-name or ACCOUNT_NAME")

    report_path = Path(args.report_path)
    owner = to_checksum_address(args.owner)

    if args.dry_run:
        smoke_amm = _resolve_smoke_amm(args.smoke_amm)
        deployer = _load_account(args.account_name).address
        with boa.fork(args.rpc_url):
            _deploy(
                deployer,
                dry_run=True,
                owner=owner,
                report_path=report_path,
                smoke_amm=smoke_amm,
            )
    else:
        acct = _load_account(args.account_name)
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _deploy(
                acct.address,
                dry_run=False,
                owner=owner,
                report_path=report_path,
                smoke_amm=None,
            )


if __name__ == "__main__":
    main()
