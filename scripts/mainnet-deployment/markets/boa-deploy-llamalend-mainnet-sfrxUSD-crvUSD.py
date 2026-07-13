#!/usr/bin/env python3
"""
Deploy the sfrxUSD/crvUSD LlamaLend V2 market on Ethereum Mainnet.

Borrowed token: crvUSD.  Collateral: sfrxUSD (Frax ERC4626 vault).

Per market this deploys, in order:
    1. Oracle stack (prices sfrxUSD in USD).
         a. OracleFromCurvePools([pool], [borrowed_idx], [collateral_idx])
         b. CrvUSDAggregatorWrapper(pool_oracle)   -> x crvUSD/USD aggregator
         c. ERC4626EMAWrapper(agg_wrapper, sfrxUSD, ema_time)  -> x vault share price
    2. SfrxUSDRateCalculator(sfrxUSD) -> per-second yield rate of the collateral.
    3. HyperbolicDynamicMP(controller, rate_calculator, curve params...).
    4. factory.create(crvUSD, sfrxUSD, ... oracle, monetary_policy, supply_limit).

HyperbolicDynamicMP binds its Controller as an immutable set in the constructor,
but the Controller is only created inside factory.create() (which itself needs
the monetary policy address).  To deploy the monetary policy *before* the market
- and avoid a post-create set_monetary_policy swap - the Controller address is
precomputed: factory.create() deploys vault -> amm -> controller as three
consecutive CREATEs, so the controller lands at address(factory, nonce + 2).
The constructor only stores the controller (it does not call it), so a
precomputed address is safe; a wrong prediction makes create() revert (fail
safe) rather than silently misconfigure.

Run:
    # dry-run against a fork
    MAINNET_RPC_URL=... python scripts/mainnet-deployment/markets/\
boa-deploy-llamalend-mainnet-sfrxUSD-crvUSD.py --dry-run --account-name <name>

    # broadcast
    MAINNET_RPC_URL=... python scripts/mainnet-deployment/markets/\
boa-deploy-llamalend-mainnet-sfrxUSD-crvUSD.py --account-name <name>
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
from eth_utils import to_canonical_address, to_checksum_address
from eth._utils.address import generate_contract_address


CHAIN_ID = 1

# --- Tokens ---
CRVUSD = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"    # borrowed
SFRXUSD = "0xcf62F905562626CfcDD2261162a51fd02Fc9c5b6"   # collateral (ERC4626 vault)
COLLATERAL = SFRXUSD

# --- Oracle config (from tmp/deploy-oracles.py: "sfrxUSD-crvUSD") ---
POOL = "0x13e12BB0E6A2f1A3d6901a59a9d585e89A6243e1"  # frxUSD/crvUSD
POOL_BORROWED_IDX = 1
POOL_COLLATERAL_IDX = 0
# Smoothing horizon of the vault-share-price EMA (seconds). 866 ~= 600s / ln(2).
EMA_TIME = 866

# --- Contract sources ---
ORACLE_FROM_CURVE_POOLS = "curve_stablecoin/price_oracles/v2/OracleFromCurvePools.vy"
CRVUSD_AGGREGATOR_WRAPPER = "curve_stablecoin/price_oracles/v2/CrvUSDAggregatorWrapper.vy"
ERC4626_EMA_WRAPPER = "curve_stablecoin/price_oracles/v2/ERC4626EMAWrapper.vy"
RATE_CALCULATOR = "curve_stablecoin/mpolicies/v2/rate_calculators/SfrxUSDRateCalculator.vy"
HYPERBOLIC_DYNAMIC_MP = "curve_stablecoin/mpolicies/v2/HyperbolicDynamicMP.vy"
LEND_FACTORY = "curve_stablecoin/lending/LendFactory.vy"
CONFIGURATOR = "curve_stablecoin/Configurator.vy"
LEND_CONTROLLER = "curve_stablecoin/lending/LendController.vy"

# --- Monetary policy curve (from tmp/deploy-hyperbolic-mp.py) ---
TARGET_UTILIZATION = 90 * 10**16  # 90%
LOW_RATIO = 5 * 10**17            # 0.5x base at 0% utilization
HIGH_RATIO = 5 * 10**18           # 5x base at 100% utilization
RATE_SHIFT = 0

# --- Market risk parameters (stable/stable) — subject to governance review ---
A = 285
FEE = int(0.002 * 10**18)                  # 0.2%
LOAN_DISCOUNT = int(0.013 * 10**18)        # 1.3%
LIQUIDATION_DISCOUNT = int(0.01 * 10**18)  # 1%
SUPPLY_LIMIT = 2**256 - 1                  # unlimited; borrow cap set separately

# --- Post-create configuration (requires factory admin / DAO vote) ---
BORROW_CAP = 28_400_000 * 10**18  # crvUSD (18 decimals)
ADMIN_FEE = 10**17                # 10%


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


def _factory_nonce(factory_addr: str) -> int:
    """Current nonce of the factory account (works on fork and network envs)."""
    getter = getattr(boa.env, "_get_nonce", None)  # NetworkEnv
    if getter is not None:
        return int(getter(factory_addr), 16)
    return boa.env.evm.vm.state.get_nonce(to_canonical_address(factory_addr))  # fork


def _predict_controller(factory_addr: str) -> str:
    """
    Controller address that factory.create() will produce.
    create() deploys vault (nonce), amm (nonce+1), controller (nonce+2).
    """
    nonce = _factory_nonce(factory_addr)
    return to_checksum_address(
        generate_contract_address(to_canonical_address(factory_addr), nonce + 2)
    )


def _deploy(
    deployer: str, dry_run: bool, report_path: Path, factory_deployment: Path
) -> None:
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    existing = json.loads(factory_deployment.read_text())
    contracts = existing.get("contracts", existing)
    factory = boa.load_partial(LEND_FACTORY).at(contracts["factory"])
    configurator = boa.load_partial(CONFIGURATOR).at(contracts["configurator"])

    # 1. Oracle stack: pool oracle -> crvUSD aggregator wrapper -> ERC4626 EMA wrapper.
    pool_oracle = boa.load_partial(ORACLE_FROM_CURVE_POOLS).deploy(
        [POOL], [POOL_BORROWED_IDX], [POOL_COLLATERAL_IDX]
    )
    agg_wrapper = boa.load_partial(CRVUSD_AGGREGATOR_WRAPPER).deploy(pool_oracle.address)
    oracle = boa.load_partial(ERC4626_EMA_WRAPPER).deploy(
        agg_wrapper.address, COLLATERAL, EMA_TIME
    )
    price = oracle.price()  # sanity-check the stack reports a sane value
    assert price > 0, "oracle price is zero"

    # 2. Rate calculator reading the live vault.
    rate_calculator = boa.load_partial(RATE_CALCULATOR).deploy(COLLATERAL)

    # 3. Monetary policy, bound to the (precomputed) controller create() will deploy.
    predicted_controller = _predict_controller(factory.address)
    monetary_policy = boa.load_partial(HYPERBOLIC_DYNAMIC_MP).deploy(
        predicted_controller,
        rate_calculator.address,
        TARGET_UTILIZATION,
        LOW_RATIO,
        HIGH_RATIO,
        RATE_SHIFT,
    )

    # 4. Create the market (deploys vault, controller, amm and wires everything).
    deployed = factory.create(
        CRVUSD,
        COLLATERAL,
        A,
        FEE,
        LOAN_DISCOUNT,
        LIQUIDATION_DISCOUNT,
        oracle.address,
        monetary_policy.address,
        SUPPLY_LIMIT,
        sender=deployer,
    )
    vault_addr, controller_addr, amm_addr = deployed
    assert to_checksum_address(controller_addr) == predicted_controller, (
        f"controller address mismatch: predicted {predicted_controller}, "
        f"got {to_checksum_address(controller_addr)}"
    )

    chain_id = CHAIN_ID
    if hasattr(boa.env, "get_chain_id"):
        chain_id = boa.env.get_chain_id()

    # Optional: borrow cap and admin fee (only if deployer is the factory admin;
    # on mainnet the DAO owns the factory, so this needs a DAO vote instead).
    borrow_cap = BORROW_CAP
    admin_fee = ADMIN_FEE
    if factory.admin() == deployer:
        controller = boa.load_partial(LEND_CONTROLLER).at(controller_addr)
        configurator.set_borrow_cap(controller, borrow_cap, sender=deployer)
        configurator.set_admin_percentage(controller, admin_fee, sender=deployer)
    else:
        borrow_cap = 0
        admin_fee = 0
        print(
            f"[SKIP] deployer {deployer} is not factory admin — borrow cap and "
            "admin fee must be set via a DAO vote"
        )

    report = {
        "chain_id": chain_id,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "market": "sfrxUSD/crvUSD",
        "factory": factory.address,
        "configurator": configurator.address,
        "pool_oracle": pool_oracle.address,
        "agg_wrapper": agg_wrapper.address,
        "price_oracle": oracle.address,
        "rate_calculator": rate_calculator.address,
        "monetary_policy": monetary_policy.address,
        "vault": vault_addr,
        "controller": controller_addr,
        "amm": amm_addr,
        "params": {
            "borrowed_token": CRVUSD,
            "collateral_token": COLLATERAL,
            "pool": POOL,
            "pool_borrowed_idx": POOL_BORROWED_IDX,
            "pool_collateral_idx": POOL_COLLATERAL_IDX,
            "ema_time": EMA_TIME,
            "A": A,
            "fee": FEE,
            "loan_discount": LOAN_DISCOUNT,
            "liquidation_discount": LIQUIDATION_DISCOUNT,
            "supply_limit": SUPPLY_LIMIT,
            "target_utilization": TARGET_UTILIZATION,
            "low_ratio": LOW_RATIO,
            "high_ratio": HIGH_RATIO,
            "rate_shift": RATE_SHIFT,
            "borrow_cap": borrow_cap,
            "admin_fee": admin_fee,
            "initial_price": price,
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    print("Market:", report["market"])
    print("Price Oracle:", oracle.address, f"(price={price / 10**18:.6f})")
    print("Rate Calculator:", rate_calculator.address)
    print("Monetary Policy:", monetary_policy.address)
    print("Vault:", vault_addr)
    print("Controller:", controller_addr)
    print("AMM:", amm_addr)
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy LlamaLend V2 sfrxUSD/crvUSD on Mainnet"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("MAINNET_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--account-name",
        default=os.environ.get("ACCOUNT_NAME"),
        help="Brownie account name",
    )
    parser.add_argument(
        "--factory-deployment",
        default="deployments/mainnet/llamalend-mainnet.jsonc",
        help="Path to the factory deployment JSON to read factory/configurator from",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/mainnet/markets/llamalend-mainnet-sfrxUSD-crvUSD.jsonc",
        help="Where to write the deployment report",
    )
    args = parser.parse_args()

    if not args.rpc_url:
        raise SystemExit("Missing --rpc-url or MAINNET_RPC_URL")

    report_path = Path(args.report_path)
    factory_deployment = Path(args.factory_deployment)
    if not factory_deployment.exists():
        raise SystemExit(f"Factory deployment not found: {factory_deployment}")

    if not args.account_name:
        raise SystemExit("Missing --account-name or ACCOUNT_NAME")

    if args.dry_run:
        deployer = _load_account(args.account_name).address
        with boa.fork(args.rpc_url):
            _deploy(
                deployer,
                dry_run=True,
                report_path=report_path,
                factory_deployment=factory_deployment,
            )
    else:
        acct = _load_account(args.account_name)
        with boa.set_env(NetworkEnv(RetryRPC(args.rpc_url))):
            boa.env.add_account(acct, force_eoa=True)
            _deploy(
                acct.address,
                dry_run=False,
                report_path=report_path,
                factory_deployment=factory_deployment,
            )


if __name__ == "__main__":
    main()
