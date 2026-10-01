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

Both liquidity-mining factories are permissionless, so the deploying account
creates the gauge and the callback here, but neither emits anything on its own:
the GaugeController has to register them and the Configurator has to attach the
callback to the market, which is what --create-vote asks the DAO for.

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

The borrow cap, the admin fee percentage and the LM callback are set through the
Configurator, which checks the factory admin - the Ownership DAO on mainnet -
and adding a gauge needs the DAO-owned GaugeController.  With --create-vote the
script therefore ends by creating an Ownership DAO vote against the contracts it
just deployed:

    set_borrow_cap, set_admin_percentage, add_gauge(vault gauge),
    set_callback(LM callback), add_gauge(LM callback)

both gauges registered with type 0 and zero weight, so emissions follow from
gauge weight votes.  On a fork the vote is created from a pranked veCRV holder,
voted through, time-travelled past the voting period and executed, so the
resulting borrow cap, admin percentage and attached callback are read back
on-chain and land in the report.  Live, the vote is created from the deploying
account (which needs to clear the DAO's proposal threshold in veCRV) and nothing
else happens - the DAO votes on it.

Use --vote-only with the saved --report-path to propose activation later without
redeploying. Incomplete reports retain confirmed addresses for manual recovery;
the script refuses to overwrite them. Dry runs use a separate default report.

--create-vote and --vote-only need an Etherscan API key (curve_dao fetches the Aragon agent and
the target ABIs from it) and, live only, a Pinata token to pin the vote
description to IPFS - a simulated vote carries the description inline.

Run:
    # dry-run against a fork
    MAINNET_RPC_URL=... python scripts/deploy/llamalend/ethereum/markets/\
reUSDsfrxUSDLP-crvUSD/deploy.py --dry-run --account-name <name>

    # dry-run, including the activation vote
    MAINNET_RPC_URL=... ETHERSCAN_API_KEY=... PINATA_TOKEN=... python scripts/deploy/llamalend/ethereum/markets/reUSDsfrxUSDLP-crvUSD/deploy.py \
--dry-run --account-name <name> --create-vote

    # broadcast
    MAINNET_RPC_URL=... python scripts/deploy/llamalend/ethereum/markets/\
reUSDsfrxUSDLP-crvUSD/deploy.py --account-name <name>
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

# --- Liquidity mining (all three already deployed, all owned by the DAO) ---
# Deploys the gauge over the vault's ERC4626 shares - CRV for lenders.
GAUGE_FACTORY = "0x64e1a69732fAC63F6790b3d8a34C5D713cC623E6"
# Deploys the callback over the AMM's collateral - CRV for borrowers.
LM_CALLBACK_FACTORY = "0x2191718CD32d02B8E60BAdFFeA33E4B5DD9A0A0D"
LM_CALLBACK_BLUEPRINT = "0x61C404B60ee9c5fB09F70F9A645DD38fE5b3A956"
GAUGE_CONTROLLER = "0x2F50D538606Fa9EDD2B11E2446BEb18C9D5846bB"
# Gauge type 0 and no initial weight: registering only, emissions follow from
# gauge weight votes.
GAUGE_TYPE = 0
GAUGE_WEIGHT = 0

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
FEE = 9_090_909_000_000_000  # 0.91% (rounded)
LOAN_DISCOUNT = 3 * 10**16  # 3%
LIQUIDATION_DISCOUNT = 25 * 10**15  # 2.5%
SUPPLY_LIMIT = 2**256 - 1  # unlimited; borrow cap set separately

# --- Post-create configuration (requires factory admin / DAO vote) ---
BORROW_CAP = 3_000_000 * 10**18  # crvUSD (18 decimals)
ADMIN_FEE = 10**17  # 10%

# --- Activation vote (the Ownership DAO owns the factory on mainnet) ---
VOTE_DAO = curve_dao.DAO.OWNERSHIP
VOTE_DESCRIPTION = (
    "Activate reUSDsfrxUSDLP-crvUSD Llamalend V2 market on ETH mainnet by "
    "setting borrow cap {borrow_cap:,} crvUSD and admin fee percentage "
    "{admin_fee:g}%, adding the vault gauge and the LM callback gauge to the "
    "gauge controller and setting the LM callback on the market."
)

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
                if (
                    status != 503
                    or attempt == 5
                    or method in ("eth_sendRawTransaction", "eth_sendTransaction")
                ):
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
    """
    Create the Ownership DAO vote that activates the market.

    Sets the borrow cap and the admin fee, registers both gauges with the
    GaugeController and attaches the LM callback to the market.  The gauge and
    the callback are deployed permissionlessly (see `_deploy`), but neither
    emits anything until it is registered here.

    On a fork the vote is also passed and executed (curve_dao.simulate votes with
    the Convex voterproxy and time-travels past voteTime), so the caller can read
    the resulting configuration straight off the controller and the AMM.
    """
    actions = [
        (configurator_addr, "set_borrow_cap", controller_addr, BORROW_CAP),
        (configurator_addr, "set_admin_percentage", controller_addr, ADMIN_FEE),
        # Lender-side gauge over the vault shares.
        (GAUGE_CONTROLLER, "add_gauge", gauge_addr, GAUGE_TYPE, GAUGE_WEIGHT),
        # Borrower-side callback: attached to the market, then registered as a
        # gauge in its own right (it reads its relative weight off the
        # GaugeController and mints through the Minter).
        (configurator_addr, "set_callback", controller_addr, lm_callback_addr),
        (GAUGE_CONTROLLER, "add_gauge", lm_callback_addr, GAUGE_TYPE, GAUGE_WEIGHT),
    ]
    description = VOTE_DESCRIPTION.format(
        borrow_cap=BORROW_CAP // 10**18, admin_fee=ADMIN_FEE / 10**16
    )
    print("Vote description:", description)

    if not dry_run:
        # Sent by the deploying account, which needs enough veCRV to propose.
        vote_id = curve_dao.create_vote(
            VOTE_DAO,
            actions,
            description,
            etherscan_api_key=etherscan_api_key,
            pinata_token=pinata_token,
            is_simulation=False,
        )
        print("Activation vote created:", vote_id)
        return vote_id

    # On a fork the description is not pinned to IPFS, so no Pinata token is
    # needed; the vote is created from a veCRV holder instead of the deployer.
    with boa.env.prank(curve_dao.addresses.CONVEX_VOTERPROXY):
        vote_id = curve_dao.create_vote(
            VOTE_DAO,
            actions,
            description,
            etherscan_api_key=etherscan_api_key,
            pinata_token=pinata_token,
            is_simulation=True,
        )
    print("Simulated activation vote:", vote_id)
    curve_dao.simulate(vote_id, VOTE_DAO, etherscan_api_key)
    return vote_id


def _write_report(path: Path, report: dict, **updates) -> None:
    report.update(updates)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n")
    temporary.replace(path)


def _activate(
    report_path: Path,
    dry_run: bool,
    etherscan_api_key: str | None,
    pinata_token: str | None,
) -> int:
    chain_id = (
        boa.env.get_chain_id()
        if hasattr(boa.env, "get_chain_id")
        else boa.env.evm.patch.chain_id
    )
    assert chain_id == CHAIN_ID, "Ethereum mainnet required"
    report = json.loads(report_path.read_text())
    assert report.get("complete"), (
        "Deployment is incomplete; reconcile the saved addresses first"
    )
    assert report["chain_id"] == CHAIN_ID
    assert dry_run or not report["dry_run"], "Cannot activate fork addresses on mainnet"
    assert not report.get("activation_vote_pending"), (
        "Reconcile the previous vote transaction first"
    )
    assert report.get("activation_vote_id") is None, "Activation vote already created"
    factory = boa.load_partial(LEND_FACTORY).at(report["factory"])
    controller = boa.load_partial(LEND_CONTROLLER).at(report["controller"])
    amm = boa.load_partial(AMM_SRC).at(report["amm"])
    lm_factory = boa.load_partial(LM_CALLBACK_FACTORY_SRC).at(LM_CALLBACK_FACTORY)
    gauge_factory = boa.loads_abi(GAUGE_FACTORY_ABI).at(GAUGE_FACTORY)
    assert controller.factory() == factory.address
    assert controller.configurator() == report["configurator"]
    assert factory.markets(factory.vaults_index(report["vault"]))[1:3] == (
        report["controller"],
        report["amm"],
    )
    assert controller.monetary_policy() == report["monetary_policy"]
    assert amm.price_oracle_contract() == report["price_oracle"]
    assert amm.coins(0) == CRVUSD and amm.coins(1) == LP_POOL
    assert amm.A() == A and amm.fee() == FEE
    assert controller.loan_discount() == LOAN_DISCOUNT
    assert controller.liquidation_discount() == LIQUIDATION_DISCOUNT
    assert report["params"]["requested_borrow_cap"] == BORROW_CAP
    assert report["params"]["requested_admin_fee"] == ADMIN_FEE
    assert gauge_factory.get_gauge_from_lp_token(report["vault"]) == report["gauge"]
    assert lm_factory.get_lm_callback_by_amm(report["amm"]) == report["lm_callback"]
    assert (
        lm_factory.get_blueprint_by_lm_callback(report["lm_callback"])
        == LM_CALLBACK_BLUEPRINT
    )
    if not dry_run:
        _write_report(report_path, report, activation_vote_pending=True)
    vote_id = _create_activation_vote(
        report["configurator"],
        report["controller"],
        report["gauge"],
        report["lm_callback"],
        dry_run,
        etherscan_api_key,
        pinata_token,
    )
    if not dry_run:
        _write_report(
            report_path,
            report,
            activation_vote_pending=False,
            activation_vote_id=vote_id,
        )
    return vote_id


def _deploy(
    deployer: str,
    dry_run: bool,
    report_path: Path,
    factory_deployment: Path,
    create_vote: bool,
    etherscan_api_key: str | None,
    pinata_token: str | None,
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
    for key in (
        "amm_blueprint",
        "controller_blueprint",
        "vault_blueprint",
        "controller_view_blueprint",
    ):
        assert getattr(factory, key)() == contracts[key], f"Unexpected {key}"
    lm_callback_factory = boa.load_partial(LM_CALLBACK_FACTORY_SRC).at(
        LM_CALLBACK_FACTORY
    )
    assert lm_callback_factory.version() == "1.0.0"
    assert not lm_callback_factory.paused(), "LM callback factory is paused"
    assert lm_callback_factory.owner() == factory.admin()
    assert lm_callback_factory.lm_callback_blueprint() == LM_CALLBACK_BLUEPRINT

    # 0. Verify the hardcoded coin layout against the live pool before
    #    deploying anything.
    _check_pool_coins(LP_POOL, LP_POOL_COINS, "LP pool (reUSD/sfrxUSD)")

    report = {
        "chain_id": chain_id,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "factory": factory.address,
        "configurator": configurator.address,
        "complete": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x") as f:
        json.dump(report, f, indent=2)

    # 1. Oracle stack: LP/reUSD -> reUSD/crvUSD -> crvUSD/USD, chained.
    lp_oracle = boa.load_partial(STABLESWAP_NG_LP_ORACLE).deploy(
        LP_POOL, LP_COIN_IDX, EMA_TIME
    )
    _write_report(report_path, report, lp_oracle=lp_oracle.address)
    reusd_adapter = boa.load_partial(REUSD_ADAPTER).deploy()
    _write_report(report_path, report, reusd_adapter=reusd_adapter.address)
    oracle = boa.load_partial(CHAIN_ORACLE).deploy(
        [lp_oracle.address, reusd_adapter.address, AGG]
    )

    _write_report(report_path, report, price_oracle=oracle.address)
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

    _write_report(report_path, report, monetary_policy=monetary_policy.address)

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
    _write_report(
        report_path, report, vault=vault_addr, controller=controller_addr, amm=amm_addr
    )
    assert to_checksum_address(controller_addr) == predicted_controller, (
        f"controller address mismatch: predicted {predicted_controller}, "
        f"got {to_checksum_address(controller_addr)}"
    )

    # 4. Liquidity mining. Both factories are permissionless, so the deployer
    #    creates the contracts; registering them is governance (see the vote).
    gauge_factory = boa.loads_abi(GAUGE_FACTORY_ABI).at(GAUGE_FACTORY)
    gauge_addr = to_checksum_address(
        str(gauge_factory.deploy_gauge(vault_addr, sender=deployer))
    )
    _write_report(report_path, report, gauge=gauge_addr)
    # One gauge per LP token: a second deploy_gauge for this vault would revert.
    assert (
        to_checksum_address(str(gauge_factory.get_gauge_from_lp_token(vault_addr)))
        == gauge_addr
    ), "gauge not registered for the vault"

    lm_callback_addr = to_checksum_address(
        str(lm_callback_factory.deploy_lm_callback(amm_addr, sender=deployer))
    )
    _write_report(report_path, report, lm_callback=lm_callback_addr)
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
    vote_id = None
    # Save the deployed market before making any governance calls.
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
        "activation_vote_id": vote_id,
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
            "requested_borrow_cap": BORROW_CAP,
            "requested_admin_fee": ADMIN_FEE,
            "borrow_cap": borrow_cap,
            "admin_fee": admin_fee,
            "gauge_factory": GAUGE_FACTORY,
            "lm_callback_factory": LM_CALLBACK_FACTORY,
            "gauge_type": GAUGE_TYPE,
            "gauge_weight": GAUGE_WEIGHT,
            "initial_price": price,
            "initial_lp_price": lp_price,
            "initial_reusd_price": reusd_price,
        },
    }

    _write_report(report_path, report, complete=True)

    # Borrow cap, admin fee and the callback: set directly if the deployer is the
    # factory admin, otherwise (mainnet, where the DAO owns the factory) through a
    # DAO vote. Registering either gauge always needs the DAO - the GaugeController
    # is DAO-owned and this script never has its admin.
    if factory.admin() == deployer:
        configurator.set_borrow_cap(controller, BORROW_CAP, sender=deployer)
        configurator.set_admin_percentage(controller, ADMIN_FEE, sender=deployer)
        configurator.set_callback(controller, lm_callback_addr, sender=deployer)
        print(
            "[SKIP] gauge registration: add_gauge on the GaugeController needs "
            "the DAO, so neither gauge is emitting yet"
        )
    elif create_vote:
        print(
            f"deployer {deployer} is not factory admin — creating the activation "
            "vote for the Ownership DAO"
        )
        vote_id = _activate(report_path, dry_run, etherscan_api_key, pinata_token)
    else:
        print(
            f"[SKIP] deployer {deployer} is not factory admin — borrow cap, admin "
            "fee, the LM callback and both gauges must be set via a DAO vote "
            "(use --vote-only with this report)"
        )

    borrow_cap = controller.borrow_cap()
    admin_fee = controller.admin_percentage()
    callback_attached = amm.liquidity_mining_callback() == lm_callback_addr
    report["params"].update(borrow_cap=borrow_cap, admin_fee=admin_fee)
    _write_report(
        report_path,
        report,
        callback_attached=callback_attached,
        activation_vote_id=vote_id,
    )

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
    if vote_id is not None:
        print("Activation vote:", vote_id)
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy LlamaLend V2 reUSD/sfrxUSD LP/crvUSD on Mainnet"
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
        "--create-vote",
        action="store_true",
        help=(
            "Create the Ownership DAO vote setting the borrow cap and admin fee "
            "for the new market (simulated end-to-end under --dry-run)"
        ),
    )
    parser.add_argument(
        "--vote-only",
        action="store_true",
        help="Create the activation vote from --report-path without deploying another market",
    )
    parser.add_argument(
        "--etherscan-api-key",
        default=os.environ.get("ETHERSCAN_API_KEY"),
        help="Etherscan API key, needed by --create-vote to fetch target ABIs",
    )
    parser.add_argument(
        "--pinata-token",
        default=os.environ.get("PINATA_TOKEN"),
        help="Pinata token, needed by --create-vote to pin the vote description",
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

    if args.vote_only and args.create_vote:
        raise SystemExit("Use either --vote-only or --create-vote")
    if (
        args.dry_run
        and not args.vote_only
        and report_path == Path(parser.get_default("report_path"))
    ):
        report_path = report_path.with_name(report_path.stem + ".dry-run.json")

    if args.create_vote or args.vote_only:
        if not args.etherscan_api_key:
            raise SystemExit(
                "--create-vote needs --etherscan-api-key or ETHERSCAN_API_KEY"
            )
        # The description is only pinned for a live vote.
        if not args.dry_run and not args.pinata_token:
            raise SystemExit("--create-vote needs --pinata-token or PINATA_TOKEN")

    if args.dry_run:
        deployer = _load_account(args.account_name).address
        with boa.fork(args.rpc_url):
            if args.vote_only:
                _activate(report_path, True, args.etherscan_api_key, args.pinata_token)
                return
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
            assert boa.env.get_chain_id() == CHAIN_ID, "Ethereum mainnet required"
            if args.vote_only:
                _activate(report_path, False, args.etherscan_api_key, args.pinata_token)
                return
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
