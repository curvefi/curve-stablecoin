#!/usr/bin/env python3
"""
Deploy the wstGBP/crvUSD LlamaLend V2 market on Ethereum Mainnet.

Borrowed token: crvUSD. Collateral: wstGBP (tGBP redemption wrapper).

Per market this deploys, in order:
    1. Oracle stack (prices wstGBP in USD):
         a. ChainlinkEMA(GBP/USD, 10 observations, 60-second interval)
         b. WstGBPFxOracle(wstGBP, ChainlinkEMA)
              -> capped burncost() in tGBP x smoothed GBP/USD; crvUSD is $1.
                 FX pricing uses only the EMA adapter, without a feed-age cutoff.
                 A NAV pause reuses the saved redemption rate while FX keeps updating.
    2. HyperbolicMP(controller, curve params...) - fixed target rate, for
       stable collateral / stable debt markets.
    3. factory.create(crvUSD, wstGBP, ... oracle, monetary_policy, supply_limit).
    4. GaugeFactory.deploy_gauge(vault) - liquidity gauge over the vault's ERC4626
       shares, i.e. the lender side of CRV emissions.

The gauge factory is permissionless. With --create-vote, the same deploying
account proposes an Ownership DAO vote to set the borrow cap and admin fee,
and register the vault gauge (type 0, zero weight). Activation requires
governance to pass and execute the vote.

The oracle checks the wrapper's gem and both token decimals. Deployment checks
the expected gem and adapter feed, plus 10 observations at 60-second intervals.

HyperbolicMP binds its Controller as an immutable set in the constructor, but
the Controller is only created inside factory.create() (which itself needs the
monetary policy address).  To deploy the monetary policy *before* the market -
and avoid a post-create set_monetary_policy swap - the Controller address is
precomputed: factory.create() deploys vault -> amm -> controller as three
consecutive CREATEs, so the controller lands at address(factory, nonce + 2).
The constructor only stores the controller (it does not call it), so a
precomputed address is safe; a wrong prediction makes create() revert (fail
safe) rather than silently misconfigure.

The deployment report is saved before proposing, then updated with the vote ID.
Existing reports are never overwritten by another deployment. Use a separate
--report-path for dry runs. --create-vote requires ETHERSCAN_API_KEY (or ETHERSCAN_KEY)
and, for live proposals, PINATA_TOKEN. Dry runs propose only on the fork.

Run:
    # dry-run against a fork
    MAINNET_RPC_URL=... python scripts/deploy/llamalend/ethereum/markets/\
wstGBP-crvUSD/deploy.py --dry-run --account-name <name>

    # broadcast
    MAINNET_RPC_URL=... python scripts/deploy/llamalend/ethereum/markets/\
wstGBP-crvUSD/deploy.py --account-name <name>
"""

import argparse
import json
import os
import time
from getpass import getpass
from pathlib import Path

import boa
import boa_solidity
import solcx
import curve_dao
from boa.network import NetworkEnv
from boa.rpc import EthereumRPC
from eth_account import account
from eth_utils import to_canonical_address, to_checksum_address
from eth._utils.address import generate_contract_address


CHAIN_ID = 1

# --- Tokens ---
CRVUSD = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"  # borrowed
WSTGBP = "0x57c3571f10767e49c9d7b60feb6c67804783b7ae"  # collateral
TGBP = "0x27f6c8289550fCE67f6B50BeD1F519966aFE5287"

# --- Oracle config ---
CHAINLINK_FEED = "0x5c0Ab2d9b5a7ed9f470386e82BB36A3613cDd4b5"
OBSERVATIONS = 10
INTERVAL = 60

# --- Liquidity gauge factory ---
# Deploys the gauge over the vault's ERC4626 shares - CRV for lenders.
GAUGE_FACTORY = "0x64e1a69732fAC63F6790b3d8a34C5D713cC623E6"

# --- Contract sources ---
CHAINLINK_EMA = "curve_stablecoin/price_oracles/v2/ChainlinkEMA.sol"
WSTGBP_FX_ORACLE = "curve_stablecoin/price_oracles/v2/WstGBPFxOracle.sol"
HYPERBOLIC_MP = "curve_stablecoin/mpolicies/v2/HyperbolicMP.vy"
LEND_FACTORY = "curve_stablecoin/lending/LendFactory.vy"
CONFIGURATOR = "curve_stablecoin/Configurator.vy"
LEND_CONTROLLER = "curve_stablecoin/lending/LendController.vy"

# --- Monetary policy curve (HyperbolicMP) — subject to governance review ---
TARGET_UTILIZATION = 90 * 10**16  # 90%
TARGET_RATE = 5 * 10**16 // (365 * 86400)  # ~5% APR (per second, 1e18-scaled)
LOW_RATIO = 5 * 10**17  # 0.5x base at 0% utilization
HIGH_RATIO = 5 * 10**18  # 5x base at 100% utilization
RATE_SHIFT = 0  # no flat shift

# --- Final market parameters (spec revision 2) ---
A = 150
FEE = 4 * 10**15  # 0.4%
LOAN_DISCOUNT = 41 * 10**15  # 4.1%
LIQUIDATION_DISCOUNT = 21 * 10**15  # 2.1%
SUPPLY_LIMIT = 2**256 - 1  # unlimited; borrow cap set separately

# --- Activation proposal (Ownership DAO) ---
BORROW_CAP = 80_000 * 10**18  # crvUSD
ADMIN_FEE = 10**17  # 10%
GAUGE_CONTROLLER = "0x2F50D538606Fa9EDD2B11E2446BEb18C9D5846bB"
VOTE_DAO = curve_dao.DAO.OWNERSHIP


def _load_account(fname: str) -> account.LocalAccount:
    path = os.path.expanduser(
        os.path.join("~", ".brownie", "accounts", fname + ".json")
    )
    with open(path, "r") as f:
        pkey = account.decode_keyfile_json(json.load(f), getpass())
        return account.Account.from_key(pkey)


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


def _create_activation_vote(
    configurator_addr: str,
    controller_addr: str,
    gauge_addr: str,
    dry_run: bool,
    etherscan_api_key: str,
    pinata_token: str | None,
) -> int:
    # Register the vault gauge with type 0 and zero initial weight.
    actions = [
        (configurator_addr, "set_borrow_cap", controller_addr, BORROW_CAP),
        (configurator_addr, "set_admin_percentage", controller_addr, ADMIN_FEE),
        (GAUGE_CONTROLLER, "add_gauge", gauge_addr, 0, 0),
    ]
    description = (
        "Activate wstGBP/crvUSD LlamaLend V2 on Ethereum: "
        f"set a {BORROW_CAP // 10**18:,} crvUSD borrow cap and "
        f"{ADMIN_FEE / 10**16:g}% admin fee, and register the vault gauge "
        "with type 0 and zero initial weight."
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
    if create_vote:
        assert boa.env.eoa == deployer, "Proposer must be the deploying account"
        dao = curve_dao.get_dao_parameters(VOTE_DAO)
        assert factory.admin() == dao["agent"], (
            "Factory admin must be the Ownership DAO"
        )
        voting = boa.from_etherscan(dao["voting"], api_key=etherscan_api_key)
        assert voting.canCreateNewVote(deployer), "Deployer is not eligible to propose"

    # 1. Smooth GBP/USD, then combine it with the capped redemption rate.
    solcx.install_solc("0.8.25")
    solcx.set_solc_version("0.8.25")
    chainlink_adapter = boa.load_partial_solc(CHAINLINK_EMA).deploy(
        CHAINLINK_FEED, OBSERVATIONS, INTERVAL
    )
    assert (
        chainlink_adapter.OBSERVATIONS() == OBSERVATIONS
        and chainlink_adapter.INTERVAL() == INTERVAL
    )
    oracle = boa.load_partial_solc(WSTGBP_FX_ORACLE).deploy(
        WSTGBP, chainlink_adapter.address
    )

    price = oracle.price()
    print(f"  wstGBP/USD: {price / 10**18:.6f}")
    assert price > 0
    assert to_checksum_address(str(oracle.WSGEM())) == to_checksum_address(WSTGBP)
    wrapper = boa.load_partial_solc(WSTGBP_FX_ORACLE, contract_name="IWstGBP").at(
        WSTGBP
    )
    assert to_checksum_address(str(wrapper.gem())) == to_checksum_address(TGBP)
    assert (
        to_checksum_address(str(oracle.CHAINLINK_ADAPTER()))
        == chainlink_adapter.address
    )
    assert to_checksum_address(
        str(chainlink_adapter.chainlinkFeed())
    ) == to_checksum_address(CHAINLINK_FEED)

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
        WSTGBP,
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

    # 4. Deploy the vault liquidity gauge permissionlessly.
    gauge_factory = boa.load_vyi("curve_stablecoin/interfaces/IGaugeFactory.vyi").at(
        GAUGE_FACTORY
    )
    gauge_addr = to_checksum_address(
        str(gauge_factory.deploy_gauge(vault_addr, sender=deployer))
    )
    # One gauge per LP token: a second deploy_gauge for this vault would revert.
    assert (
        to_checksum_address(str(gauge_factory.get_gauge_from_lp_token(vault_addr)))
        == gauge_addr
    ), "gauge not registered for the vault"

    controller = boa.load_partial(LEND_CONTROLLER).at(controller_addr)
    # Read the initial settings for the deployment report.
    borrow_cap = controller.borrow_cap()
    admin_fee = controller.admin_percentage()
    report = {
        "chain_id": chain_id,
        "deployer": deployer,
        "dry_run": dry_run,
        "timestamp": int(time.time()),
        "market": "wstGBP/crvUSD",
        "factory": factory.address,
        "configurator": configurator.address,
        "chainlink_adapter": chainlink_adapter.address,
        "price_oracle": oracle.address,
        "monetary_policy": monetary_policy.address,
        "vault": vault_addr,
        "controller": controller_addr,
        "amm": amm_addr,
        "gauge": gauge_addr,
        "params": {
            "borrowed_token": CRVUSD,
            "collateral_token": WSTGBP,
            "gem": TGBP,
            "chainlink_feed": CHAINLINK_FEED,
            "observations": OBSERVATIONS,
            "interval": INTERVAL,
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
            "initial_price": price,
            "initial_adapter_price": chainlink_adapter.price(),
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
            dry_run,
            etherscan_api_key,
            pinata_token,
        )
        report["activation_vote_id"] = vote_id
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        print("Activation vote:", vote_id)

    print(f"Controller borrow cap    : {borrow_cap / 10**18:,.0f} crvUSD")
    print(f"Controller admin fee     : {admin_fee / 10**16:g}%")
    print("Market:", report["market"])
    print("GBP/USD EMA:", chainlink_adapter.address)
    print("Price Oracle:", oracle.address, f"(price={price / 10**18:.6f})")
    print("Monetary Policy:", monetary_policy.address)
    print("Vault:", vault_addr)
    print("Controller:", controller_addr)
    print("AMM:", amm_addr)
    print("Gauge (vault):", gauge_addr)
    print("Report:", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy LlamaLend V2 wstGBP/crvUSD on Mainnet"
    )
    parser.add_argument("--rpc-url", default=os.environ.get("MAINNET_RPC_URL"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--create-vote",
        action="store_true",
        help="Propose market activation from the deploying account after deployment",
    )
    parser.add_argument(
        "--etherscan-api-key",
        default=os.environ.get("ETHERSCAN_API_KEY") or os.environ.get("ETHERSCAN_KEY"),
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
        default="deployments/llamalend/ethereum/markets/wstGBP-crvUSD.jsonc",
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
        with boa.set_env(NetworkEnv(EthereumRPC(args.rpc_url))):
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
