#!/usr/bin/env python3
"""
Deploy the reUSD/sfrxUSD LP LlamaLend V2 market on Ethereum Mainnet.

Borrowed token: crvUSD.  Collateral: the reUSD/sfrxUSD StableSwap-NG LP token
(a StableSwap-NG pool is its own LP token, so the collateral address is the
pool address).

Per market this deploys, in order:
    1. Oracle stack (prices the LP token in USD), chained with ChainOracle:
         a. StableSwapNGLPOracle(reUSD/sfrxUSD pool, reUSD idx, ema_time)
              -> LP price quoted in reUSD, with the pool's virtual price
                 asymmetrically EMA-dampened against single-block pumps.
         b. ReusdCrvUSDAdapter()
              -> min(1e18, ReusdOracle.priceAsCrvusd()), in crvUSD per reUSD.
                 Reuses the existing redemption-based feed and preserves its
                 redemption floor, which can mask market losses. No added EMA.
         c. AGG (already deployed crvUSD stable aggregator)
              -> crvUSD/USD, which is what makes the result USD-denominated.
       ChainOracle multiplies the legs:
              LP/reUSD  x  reUSD/crvUSD  x  crvUSD/USD  =  LP/USD
    2. HyperbolicMP(controller, curve params...) - fixed target rate, for
       like-kind (stable collateral / stable debt) markets.
    3. factory.create(crvUSD, LP token, ... oracle, monetary_policy, supply_limit).
    4. GaugeFactory.deploy_gauge(vault) - liquidity gauge over the vault's ERC4626
       shares, i.e. the lender side of CRV emissions.
    5. LMCallbackFactory.deploy_lm_callback(amm) - gauge-like callback over the
       AMM's collateral, i.e. the borrower side.

Both liquidity-mining factories are permissionless. With --create-vote, the
deploying account also proposes an Ownership DAO vote to set the borrow cap
and admin fee, attach the callback and register both gauges with type 0 and
zero initial weight. The account must be eligible to propose. Activation
requires governance to pass and execute the vote.

Coin layout of the collateral pool (2 coins; `coins(2)` reverts):

    reUSD/sfrxUSD  0xed785Af6...  coin 0 = reUSD, coin 1 = sfrxUSD
so LP_COIN_IDX = 0. The layout is asserted against `coins(i)` before deployment.
The reUSD adapter fixes its feed address in the contract; the feed obtains its
market price from the reUSD/scrvUSD pool and applies the redemption floor.

HyperbolicMP binds its Controller as an immutable set in the constructor, but
the Controller is only created inside factory.create() (which itself needs the
monetary policy address).  To deploy the monetary policy *before* the market -
and avoid a post-create set_monetary_policy swap - the Controller address is
precomputed: factory.create() deploys vault -> amm -> controller as three
consecutive CREATEs, so the controller lands at address(factory, nonce + 2).
The constructor only stores the controller (it does not call it), so a
precomputed address is safe; a wrong prediction makes create() revert (fail
safe) rather than silently misconfigure.

The deployment report records deployed addresses and initial market settings
before proposing, then adds the vote ID. Existing reports are never overwritten
by another deployment. Use a separate --report-path for dry runs.

--create-vote requires ETHERSCAN_API_KEY and, for live proposals, PINATA_TOKEN.
A dry run creates the proposal on the fork without pinning its description.

Run:
    # dry-run against a fork
    MAINNET_RPC_URL=... python scripts/deploy/llamalend/ethereum/markets/\
reUSDsfrxUSDLP-crvUSD/deploy.py --dry-run --account-name <name>

    # broadcast
    MAINNET_RPC_URL=... python scripts/deploy/llamalend/ethereum/markets/\
reUSDsfrxUSDLP-crvUSD/deploy.py --account-name <name>

    # deploy and propose activation from the same account (add --dry-run for a fork)
    MAINNET_RPC_URL=... ETHERSCAN_API_KEY=... PINATA_TOKEN=... python scripts/deploy/llamalend/ethereum/markets/reUSDsfrxUSDLP-crvUSD/deploy.py \
--account-name <name> --create-vote
"""

import argparse
import json
import os
import time
from getpass import getpass
from pathlib import Path

import boa
import curve_dao
import requests
from boa.network import NetworkEnv
from boa.rpc import EthereumRPC
from eth_account import account
from eth_utils import to_canonical_address, to_checksum_address
from eth._utils.address import generate_contract_address


CHAIN_ID = 1

# --- Tokens ---
CRVUSD = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"  # borrowed
REUSD = "0x57aB1E0003F623289CD798B1824Be09a793e4Bec"  # LP price numeraire
SFRXUSD = "0xcf62F905562626CfcDD2261162a51fd02Fc9c5b6"  # collateral pool coin

# --- Collateral pool and its coin layout ---
# Collateral pool. Its LP token *is* the pool, and that is what is collateralised.
LP_POOL = "0xed785Af60bEd688baa8990cD5c4166221599A441"  # reUSD/sfrxUSD
LP_POOL_COINS = {0: REUSD, 1: SFRXUSD}

# --- LP quote index (coin layout asserted against the chain before use) ---
# LP price is quoted in the underlying asset of this coin; reUSD is a plain ERC20,
# so the LP token comes out priced in reUSD.
LP_COIN_IDX = 0  # reUSD

# crvUSD stable aggregator, already deployed (same address CrvUSDAggregatorWrapper pins).
AGG = "0x18672b1b0c623a30089A280Ed9256379fb0E4E62"

# --- Liquidity-mining factories and callback blueprint ---
# Deploys the gauge over the vault's ERC4626 shares - CRV for lenders.
GAUGE_FACTORY = "0x64e1a69732fAC63F6790b3d8a34C5D713cC623E6"
# Deploys the callback over the AMM's collateral - CRV for borrowers.
LM_CALLBACK_FACTORY = "0x2191718CD32d02B8E60BAdFFeA33E4B5DD9A0A0D"
LM_CALLBACK_BLUEPRINT = "0x61C404B60ee9c5fB09F70F9A645DD38fE5b3A956"
# Smoothing horizon of the LP virtual-price EMA (seconds). 866 ~= 600s / ln(2).
EMA_TIME = 866

# --- Contract sources ---
STABLESWAP_NG_LP_ORACLE = "curve_stablecoin/price_oracles/v2/StableSwapNGLPOracle.vy"
REUSD_ADAPTER = "curve_stablecoin/price_oracles/v2/adapters/ReusdCrvUSDAdapter.vy"
CHAIN_ORACLE = "curve_stablecoin/price_oracles/v2/ChainOracle.vy"
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
A = 440
FEE = 9_090_909_000_000_000  # 0.91% rounded; below the AMM's 4/A cap
LOAN_DISCOUNT = 3 * 10**16  # 3%
LIQUIDATION_DISCOUNT = 25 * 10**15  # 2.5%
SUPPLY_LIMIT = 2**256 - 1  # unlimited; borrow cap set separately

# --- Activation proposal (Ownership DAO) ---
BORROW_CAP = 3_000_000 * 10**18  # crvUSD
ADMIN_FEE = 10**17  # 10%
GAUGE_CONTROLLER = "0x2F50D538606Fa9EDD2B11E2446BEb18C9D5846bB"
VOTE_DAO = curve_dao.DAO.OWNERSHIP

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
    """
    Assert a pool's coins sit at the indexes hardcoded above.

    The whole oracle chain hinges on this layout - reUSD has to be the coin the
    LP oracle quotes in and the coin the reUSD adapter prices - so it is
    checked against the live pool before anything is deployed.
    """
    pool = boa.loads_abi(POOL_ABI).at(pool_addr)
    for idx, token in expected.items():
        actual = to_checksum_address(str(pool.coins(idx)))
        assert actual == to_checksum_address(token), (
            f"{label} ({pool_addr}) coin {idx} is {actual}, expected {token}"
        )
    print(f"{label} coins verified:", {i: t for i, t in expected.items()})


def _create_activation_vote(
    configurator_addr: str,
    controller_addr: str,
    gauge_addr: str,
    lm_callback_addr: str,
    dry_run: bool,
    etherscan_api_key: str,
    pinata_token: str | None,
) -> int:
    # Register both gauges with type 0 and zero initial weight.
    actions = [
        (configurator_addr, "set_borrow_cap", controller_addr, BORROW_CAP),
        (configurator_addr, "set_admin_percentage", controller_addr, ADMIN_FEE),
        (GAUGE_CONTROLLER, "add_gauge", gauge_addr, 0, 0),
        (configurator_addr, "set_callback", controller_addr, lm_callback_addr),
        (GAUGE_CONTROLLER, "add_gauge", lm_callback_addr, 0, 0),
    ]
    description = (
        "Activate reUSD/sfrxUSD LP/crvUSD LlamaLend V2 on Ethereum: "
        f"set a {BORROW_CAP // 10**18:,} crvUSD borrow cap and "
        f"{ADMIN_FEE / 10**16:g}% admin fee, attach the LM callback and "
        "register the vault and callback gauges with type 0 and zero initial weight."
    )
    return curve_dao.create_vote(
        VOTE_DAO,
        actions,
        description,
        etherscan_api_key=etherscan_api_key,
        pinata_token=pinata_token,
        is_simulation=dry_run,
    )


def _deploy(
    deployer: str,
    dry_run: bool,
    report_path: Path,
    factory_deployment: Path,
    create_vote: bool = False,
    etherscan_api_key: str | None = None,
    pinata_token: str | None = None,
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
    assert lm_callback_factory.owner() == factory.admin()
    assert lm_callback_factory.lm_callback_blueprint() == LM_CALLBACK_BLUEPRINT

    if create_vote:
        assert boa.env.eoa == deployer, "Proposer must be the deploying account"
        dao = curve_dao.get_dao_parameters(VOTE_DAO)
        assert factory.admin() == dao["agent"], (
            "Factory admin must be the Ownership DAO"
        )
        voting = boa.from_etherscan(dao["voting"], api_key=etherscan_api_key)
        assert voting.canCreateNewVote(deployer), "Deployer is not eligible to propose"

    # 0. Verify the hardcoded coin layout against the live pool before
    #    deploying anything.
    _check_pool_coins(LP_POOL, LP_POOL_COINS, "LP pool (reUSD/sfrxUSD)")

    # 1. Oracle stack: LP/reUSD -> reUSD/crvUSD -> crvUSD/USD, chained.
    lp_oracle = boa.load_partial(STABLESWAP_NG_LP_ORACLE).deploy(
        LP_POOL, LP_COIN_IDX, EMA_TIME
    )
    reusd_adapter = boa.load_partial(REUSD_ADAPTER).deploy()
    oracle = boa.load_partial(CHAIN_ORACLE).deploy(
        [lp_oracle.address, reusd_adapter.address, AGG]
    )

    lp_price = lp_oracle.price()
    reusd_price = reusd_adapter.price()
    price = oracle.price()
    print(f"  LP/reUSD    : {lp_price / 10**18:.6f}")
    print(f"  reUSD/crvUSD: {reusd_price / 10**18:.6f} (capped redemption feed)")
    print(f"  LP/USD      : {price / 10**18:.6f}")
    assert 0 < reusd_price <= 10**18
    assert price > 0
    assert [oracle.ORACLES(i) for i in range(3)] == [
        lp_oracle.address,
        reusd_adapter.address,
        AGG,
    ]

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
        LP_POOL,  # the StableSwap-NG pool is its own LP token
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
        "market": "reUSD/sfrxUSD LP/crvUSD",
        "factory": factory.address,
        "configurator": configurator.address,
        "lp_oracle": lp_oracle.address,
        "reusd_adapter": reusd_adapter.address,
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
            "collateral_token": LP_POOL,
            "lp_pool": LP_POOL,
            "lp_coin_idx": LP_COIN_IDX,
            "reusd_feed": reusd_adapter.REUSD_FEED(),
            "reusd": REUSD,
            "agg": AGG,
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
            "initial_lp_price": lp_price,
            "initial_reusd_price": reusd_price,
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x") as f:
        f.write(json.dumps(report, indent=2) + "\n")

    if create_vote:
        vote_id = _create_activation_vote(
            configurator.address,
            controller_addr,
            gauge_addr,
            lm_callback_addr,
            dry_run,
            etherscan_api_key,
            pinata_token,
        )
        report["activation_vote_id"] = vote_id
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print("Activation vote:", vote_id)

    print(f"Controller borrow cap    : {borrow_cap / 10**18:,.0f} crvUSD")
    print(f"Controller admin fee     : {admin_fee / 10**16:g}%")
    print(f"AMM callback             : {amm.liquidity_mining_callback()}")
    print("Market:", report["market"])
    print("LP Oracle:", lp_oracle.address)
    print("reUSD Adapter:", reusd_adapter.address)
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
        description="Deploy LlamaLend V2 reUSD/sfrxUSD LP/crvUSD on Mainnet"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("MAINNET_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--create-vote",
        action="store_true",
        help="Propose market activation from the deploying account after deployment",
    )
    parser.add_argument(
        "--etherscan-api-key", default=os.environ.get("ETHERSCAN_API_KEY")
    )
    parser.add_argument("--pinata-token", default=os.environ.get("PINATA_TOKEN"))
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
        default=("deployments/llamalend/ethereum/markets/reUSDsfrxUSDLP-crvUSD.jsonc"),
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

    if args.create_vote:
        if not args.etherscan_api_key:
            raise SystemExit(
                "--create-vote needs --etherscan-api-key or ETHERSCAN_API_KEY"
            )
        if not args.dry_run and not args.pinata_token:
            raise SystemExit("--create-vote needs --pinata-token or PINATA_TOKEN")

    if args.dry_run:
        deployer = _load_account(args.account_name).address
        with boa.fork(args.rpc_url):
            _deploy(
                deployer,
                dry_run=True,
                report_path=report_path,
                factory_deployment=factory_deployment,
                create_vote=args.create_vote,
                etherscan_api_key=args.etherscan_api_key,
                pinata_token=args.pinata_token,
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
                create_vote=args.create_vote,
                etherscan_api_key=args.etherscan_api_key,
                pinata_token=args.pinata_token,
            )


if __name__ == "__main__":
    main()
