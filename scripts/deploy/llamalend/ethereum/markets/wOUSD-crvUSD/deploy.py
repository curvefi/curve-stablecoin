#!/usr/bin/env python3
"""
Deploy the wOUSD/crvUSD LlamaLend V2 market on Ethereum Mainnet.

Borrowed token: crvUSD. Collateral: wOUSD (OUSD ERC4626 wrapper).

Per market this deploys, in order:
    1. Oracle stack (prices wOUSD in USD):
         a. OracleFromCurvePools(OUSD/USDC pool, USDC idx, OUSD idx)
              -> OUSD/USDC, using the pool's own EMA. USDC is $1.
         b. ERC4626EMAWrapper(pool oracle, wOUSD, 866)
              -> OUSD/USDC x wOUSD share price. Share-price increases are
                 smoothed; falls pass through immediately.
    2. HyperbolicMP(controller, curve params...) - fixed target rate, for
       like-kind (stable collateral / stable debt) markets.
    3. factory.create(crvUSD, wOUSD, ... oracle, monetary_policy, supply_limit).
    4. GaugeFactory.deploy_gauge(vault) - liquidity gauge over the vault's ERC4626
       shares, i.e. the lender side of CRV emissions.
    5. LMCallbackFactory.deploy_lm_callback(amm) - gauge-like callback over the
       AMM's collateral, i.e. the borrower side.

Both liquidity-mining factories are permissionless. The market starts with a
zero borrow cap and unattached callback. Governance must activate it separately.

The OUSD/USDC pool has coin 0 = OUSD, coin 1 = USDC. Its price_oracle(0)
returns USDC in OUSD, so OracleFromCurvePools inverts it. The coin order is
checked before deploying anything.

HyperbolicMP binds its Controller as an immutable set in the constructor, but
the Controller is only created inside factory.create() (which itself needs the
monetary policy address).  To deploy the monetary policy *before* the market -
and avoid a post-create set_monetary_policy swap - the Controller address is
precomputed: factory.create() deploys vault -> amm -> controller as three
consecutive CREATEs, so the controller lands at address(factory, nonce + 2).
The constructor only stores the controller (it does not call it), so a
precomputed address is safe; a wrong prediction makes create() revert (fail
safe) rather than silently misconfigure.

The deployment report records deployed addresses and initial market settings.
Existing reports are never overwritten. Use a separate --report-path for dry runs.

Run:
    # dry-run against a fork
    MAINNET_RPC_URL=... python scripts/deploy/llamalend/ethereum/markets/\
wOUSD-crvUSD/deploy.py --dry-run --account-name <name>

    # broadcast
    MAINNET_RPC_URL=... python scripts/deploy/llamalend/ethereum/markets/\
wOUSD-crvUSD/deploy.py --account-name <name>
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
CRVUSD = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"  # borrowed
WOUSD = "0xD2af830E8CBdFed6CC11Bab697bB25496ed6FA62"  # collateral
OUSD = "0x2A8E1E676Ec238d8A992307B495B45B3FEAA5e86"
USDC = "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"

# --- Pool and oracle config ---
POOL = "0x6d18E1a7faeB1F0467A77C0d293872ab685426dc"  # OUSD/USDC NG
POOL_COINS = {0: OUSD, 1: USDC}
POOL_BORROWED_IDX = 1  # USDC = $1
POOL_COLLATERAL_IDX = 0  # OUSD

# --- Liquidity-mining factories and callback blueprint ---
# Deploys the gauge over the vault's ERC4626 shares - CRV for lenders.
GAUGE_FACTORY = "0x64e1a69732fAC63F6790b3d8a34C5D713cC623E6"
# Deploys the callback over the AMM's collateral - CRV for borrowers.
LM_CALLBACK_FACTORY = "0x916E2B5E3Df268Ce2348265d2AAD4BB9f2B3dFA0"
LM_CALLBACK_BLUEPRINT = "0x0fDFE9c8F16AffF693EA16544d6d1Bac555343c4"
# Share-price upside EMA horizon. 866 seconds gives about a 10-minute half-life.
EMA_TIME = 866

# --- Contract sources ---
ORACLE_FROM_CURVE_POOLS = "curve_stablecoin/price_oracles/v2/OracleFromCurvePools.vy"
ERC4626_EMA_WRAPPER = "curve_stablecoin/price_oracles/v2/ERC4626EMAWrapper.vy"
HYPERBOLIC_MP = "curve_stablecoin/mpolicies/v2/HyperbolicMP.vy"
LEND_FACTORY = "curve_stablecoin/lending/LendFactory.vy"
CONFIGURATOR = "curve_stablecoin/Configurator.vy"
LEND_CONTROLLER = "curve_stablecoin/lending/LendController.vy"
LM_CALLBACK_FACTORY_SRC = "curve_stablecoin/lm_callback/LMCallbackFactory.vy"
LM_CALLBACK_SRC = "curve_stablecoin/lm_callback/LMCallback.vy"
AMM_SRC = "curve_stablecoin/AMM.vy"

# --- Monetary policy curve (HyperbolicMP) — subject to governance review ---
TARGET_UTILIZATION = 90 * 10**16  # 90%
TARGET_RATE = 5 * 10**16 // (365 * 86400)  # ~5% APR (per second, 1e18-scaled)
LOW_RATIO = 5 * 10**17  # 0.5x base at 0% utilization
HIGH_RATIO = 5 * 10**18  # 5x base at 100% utilization
RATE_SHIFT = 0  # no flat shift

# --- Market risk parameters (stable/stable) — subject to governance review ---
A = 772
FEE = 39 * 10**14  # 0.39%; below the AMM's 4/A cap
LOAN_DISCOUNT = 13 * 10**15  # 1.3%
LIQUIDATION_DISCOUNT = 8 * 10**15  # 0.8%
SUPPLY_LIMIT = 2**256 - 1  # unlimited; borrow cap set separately

# Minimal ABI for reading pool coins.
POOL_ABI = json.dumps(
    [
        {
            "name": "coins",
            "type": "function",
            "stateMutability": "view",
            "inputs": [{"name": "arg0", "type": "uint256"}],
            "outputs": [{"name": "", "type": "address"}],
        }
    ]
)


# Minimal ABI for the gauge factory (only the two entry points used here).
GAUGE_FACTORY_ABI = json.dumps(
    [
        {
            "name": "deploy_gauge",
            "type": "function",
            "stateMutability": "nonpayable",
            "inputs": [{"name": "_lp_token", "type": "address"}],
            "outputs": [{"name": "", "type": "address"}],
        },
        {
            "name": "get_gauge_from_lp_token",
            "type": "function",
            "stateMutability": "view",
            "inputs": [{"name": "arg0", "type": "address"}],
            "outputs": [{"name": "", "type": "address"}],
        },
    ]
)


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


def _check_pool_coins(pool_addr: str, expected: dict[int, str], label: str) -> None:
    """Assert the OUSD/USDC coin order used by the pool oracle."""
    pool = boa.loads_abi(POOL_ABI).at(pool_addr)
    for idx, token in expected.items():
        actual = to_checksum_address(str(pool.coins(idx)))
        assert actual == to_checksum_address(token), (
            f"{label} ({pool_addr}) coin {idx} is {actual}, expected {token}"
        )
    print(f"{label} coins verified:", {i: t for i, t in expected.items()})


def _deploy(
    deployer: str,
    dry_run: bool,
    report_path: Path,
    factory_deployment: Path,
) -> None:
    if report_path.exists():
        raise SystemExit(f"Deployment report already exists: {report_path}")
    chain_id = (
        boa.env.get_chain_id()
        if hasattr(boa.env, "get_chain_id")
        else boa.env.evm.patch.chain_id
    )
    assert chain_id == CHAIN_ID, "Ethereum mainnet required"
    if dry_run:
        boa.env.eoa = deployer
        boa.env.set_balance(deployer, 10**30)
    else:
        boa.env.suppress_debug_tt()

    existing = json.loads(factory_deployment.read_text())
    contracts = existing.get("contracts", existing)
    factory = boa.load_partial(LEND_FACTORY).at(contracts["factory"])
    configurator = boa.load_partial(CONFIGURATOR).at(contracts["configurator"])
    assert not existing.get("dry_run"), "Factory deployment is a dry-run report"
    assert existing["chain_id"] == CHAIN_ID
    assert configurator.default_admin() == factory.admin()
    assert not factory.paused(), "Lending factory is paused"
    lm_callback_factory = boa.load_partial(LM_CALLBACK_FACTORY_SRC).at(
        LM_CALLBACK_FACTORY
    )
    assert lm_callback_factory.version() == "1.0.0"
    assert not lm_callback_factory.paused(), "LM callback factory is paused"
    assert lm_callback_factory.lm_callback_blueprint() == LM_CALLBACK_BLUEPRINT

    # 0. Verify the hardcoded coin layout against the live pool before
    #    deploying anything.
    _check_pool_coins(POOL, POOL_COINS, "OUSD/USDC pool")

    # 1. Pool OUSD/USDC EMA -> wOUSD share-price EMA. USDC is counted as $1.
    pool_oracle = boa.load_partial(ORACLE_FROM_CURVE_POOLS).deploy(
        [POOL], [POOL_BORROWED_IDX], [POOL_COLLATERAL_IDX]
    )
    oracle = boa.load_partial(ERC4626_EMA_WRAPPER).deploy(
        pool_oracle.address, WOUSD, EMA_TIME
    )

    ousd_price = pool_oracle.price()
    price = oracle.price()
    print(f"  OUSD/USDC: {ousd_price / 10**18:.6f}")
    print(f"  wOUSD/USD : {price / 10**18:.6f}")
    assert ousd_price > 0
    assert price > 0
    assert oracle.ORACLE() == pool_oracle.address
    assert oracle.VAULT() == WOUSD

    # 2. Monetary policy, bound to the (precomputed) controller create() will deploy.
    predicted_controller = _predict_controller(factory.address)
    monetary_policy = boa.load_partial(HYPERBOLIC_MP).deploy(
        predicted_controller,
        TARGET_UTILIZATION,
        TARGET_RATE,
        LOW_RATIO,
        HIGH_RATIO,
        RATE_SHIFT,
    )

    # 3. Create the market (deploys vault, controller, amm and wires everything).
    assert _predict_controller(factory.address) == predicted_controller, (
        "Factory nonce changed; deploy a new monetary policy before creating the market"
    )
    deployed = factory.create(
        CRVUSD,
        WOUSD,
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

    # 4. Deploy the liquidity gauge and LM callback permissionlessly.
    gauge_factory = boa.loads_abi(GAUGE_FACTORY_ABI).at(GAUGE_FACTORY)
    gauge_addr = to_checksum_address(
        str(gauge_factory.deploy_gauge(vault_addr, sender=deployer))
    )
    # One gauge per LP token: a second deploy_gauge for this vault would revert.
    assert (
        to_checksum_address(str(gauge_factory.get_gauge_from_lp_token(vault_addr)))
        == gauge_addr
    ), "gauge not registered for the vault"

    lm_callback_addr = to_checksum_address(
        str(lm_callback_factory.deploy_lm_callback(amm_addr, sender=deployer))
    )
    assert lm_callback_factory.is_valid_gauge(lm_callback_addr), (
        "LM callback not registered by its factory"
    )
    assert lm_callback_factory.get_lm_callback_by_amm(amm_addr) == lm_callback_addr
    assert (
        lm_callback_factory.get_blueprint_by_lm_callback(lm_callback_addr)
        == LM_CALLBACK_BLUEPRINT
    )
    lm_callback = boa.load_partial(LM_CALLBACK_SRC).at(lm_callback_addr)
    # The other direction of the gauge round trip: the callback names its factory
    assert to_checksum_address(str(lm_callback.factory())) == to_checksum_address(
        LM_CALLBACK_FACTORY
    ), "LM callback points at another factory"
    assert to_checksum_address(str(lm_callback.AMM())) == to_checksum_address(
        amm_addr
    ), "LM callback bound to the wrong AMM"

    controller = boa.load_partial(LEND_CONTROLLER).at(controller_addr)
    # Read the initial settings for the deployment report.
    borrow_cap = controller.borrow_cap()
    admin_fee = controller.admin_percentage()
    amm = boa.load_partial(AMM_SRC).at(amm_addr)
    attached_callback = to_checksum_address(str(amm.liquidity_mining_callback()))
    callback_attached = attached_callback == lm_callback_addr

    report = {
        "chain_id": chain_id,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "market": "wOUSD/crvUSD",
        "factory": factory.address,
        "configurator": configurator.address,
        "pool_oracle": pool_oracle.address,
        "price_oracle": oracle.address,
        "monetary_policy": monetary_policy.address,
        "vault": vault_addr,
        "controller": controller_addr,
        "amm": amm_addr,
        "gauge": gauge_addr,
        "lm_callback": lm_callback_addr,
        "callback_attached": callback_attached,
        "params": {
            "borrowed_token": CRVUSD,
            "collateral_token": WOUSD,
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
            "target_rate": TARGET_RATE,
            "low_ratio": LOW_RATIO,
            "high_ratio": HIGH_RATIO,
            "rate_shift": RATE_SHIFT,
            "borrow_cap": borrow_cap,
            "admin_fee": admin_fee,
            "gauge_factory": GAUGE_FACTORY,
            "lm_callback_factory": LM_CALLBACK_FACTORY,
            "initial_price": price,
            "initial_ousd_price": ousd_price,
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x") as f:
        f.write(json.dumps(report, indent=2) + "\n")

    print(f"Controller borrow cap    : {borrow_cap / 10**18:,.0f} crvUSD")
    print(f"Controller admin fee     : {admin_fee / 10**16:g}%")
    print(f"AMM callback             : {amm.liquidity_mining_callback()}")
    print("Market:", report["market"])
    print("Pool Oracle:", pool_oracle.address)
    print("Price Oracle:", oracle.address, f"(price={price / 10**18:.6f})")
    print("Monetary Policy:", monetary_policy.address)
    print("Vault:", vault_addr)
    print("Controller:", controller_addr)
    print("AMM:", amm_addr)
    print("Gauge (vault):", gauge_addr)
    print(
        "LM Callback (AMM):",
        lm_callback_addr,
        "(attached)" if callback_attached else "(not attached yet)",
    )
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy LlamaLend V2 wOUSD/crvUSD on Mainnet"
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
        default="deployments/llamalend/ethereum/factory.jsonc",
        help="Path to the factory deployment JSON to read factory/configurator from",
    )
    parser.add_argument(
        "--report-path",
        default="deployments/llamalend/ethereum/markets/wOUSD-crvUSD.jsonc",
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
