import importlib.util
import json
import os
from pathlib import Path

import boa
import pytest
from vyper.compiler.output import build_abi_output

from tests.forked.settings import WEB3_PROVIDER_URL
from tests.utils.deployers import ERC20_MOCK_DEPLOYER


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "scripts/deploy/llamalend/ethereum/markets/reUSDsfrxUSDLP-crvUSD/deploy.py"
)
FACTORY_REPORT = ROOT / "deployments/llamalend/ethereum/factory.jsonc"
WAD = 10**18


@pytest.fixture(scope="module")
def deploy():
    spec = importlib.util.spec_from_file_location("reusd_lp_deploy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def market(deploy, tmp_path_factory):
    assert WEB3_PROVIDER_URL, "Set WEB3_PROVIDER_URL"
    with boa.fork(WEB3_PROVIDER_URL, block_identifier=26_093_879, allow_dirty=True):
        path = tmp_path_factory.mktemp("reusd") / "deployment.json"
        deploy._deploy(
            boa.env.generate_address("deployer"),
            True,
            path,
            FACTORY_REPORT,
            False,
            None,
            None,
        )
        yield path, json.loads(path.read_text())


def test_deployment(deploy, market):
    _, report = market
    adapter = boa.load_partial(deploy.REUSD_ADAPTER).at(report["reusd_adapter"])
    oracle = boa.load_partial(deploy.CHAIN_ORACLE).at(report["price_oracle"])
    lp = boa.load_partial(deploy.STABLESWAP_NG_LP_ORACLE).at(report["lp_oracle"])
    amm = boa.load_partial(deploy.AMM_SRC).at(report["amm"])
    controller = boa.load_partial(deploy.LEND_CONTROLLER).at(report["controller"])
    mp = boa.load_partial(deploy.HYPERBOLIC_MP).at(report["monetary_policy"])
    lm_factory = boa.load_partial(deploy.LM_CALLBACK_FACTORY_SRC).at(
        deploy.LM_CALLBACK_FACTORY
    )
    callback = boa.load_partial(deploy.LM_CALLBACK_SRC).at(report["lm_callback"])
    agg = boa.loads_abi(
        '[{"name":"price","inputs":[],"outputs":[{"type":"uint256"}],'
        '"stateMutability":"view","type":"function"}]'
    ).at(deploy.AGG)
    with boa.env.anchor():
        assert [oracle.ORACLES(i) for i in range(3)] == [
            lp.address,
            adapter.address,
            deploy.AGG,
        ]
        assert amm.price_oracle_contract() == oracle.address
        assert lp.POOL() == deploy.LP_POOL and lp.COIN_IDX() == 0
        assert report["params"]["ema_time"] == 866
        assert report["params"]["reusd_feed"] == adapter.REUSD_FEED()
        assert 0 < adapter.price() <= WAD
        composed = (lp.price() * adapter.price() // WAD) * agg.price() // WAD
        assert oracle.price() == oracle.price_w() == composed == amm.price_oracle()
        assert amm.coins(0) == deploy.CRVUSD and amm.coins(1) == deploy.LP_POOL
        assert amm.A() == 440
        assert amm.fee() == 9_090_909_000_000_000 <= 4 * WAD // 440
        assert controller.loan_discount() == 3 * 10**16
        assert controller.liquidation_discount() == 25 * 10**15
        assert controller.configurator() == report["configurator"]
        assert mp.CONTROLLER() == controller.address
        assert controller.borrow_cap() == 0
        assert int(str(amm.liquidity_mining_callback()), 16) == 0
        assert callback.factory() == deploy.LM_CALLBACK_FACTORY
        assert callback.AMM() == amm.address
        assert callback.version() == lm_factory.version() == "1.0.0"
        assert lm_factory.get_lm_callback_by_amm(amm) == callback.address
        assert (
            lm_factory.get_blueprint_by_lm_callback(callback)
            == deploy.LM_CALLBACK_BLUEPRINT
        )


def test_report_cannot_be_overwritten(deploy, market):
    path, report = market
    original = path.read_bytes()
    with pytest.raises(SystemExit, match="already exists"):
        deploy._deploy(report["deployer"], True, path, Path(), False, None, None)
    assert path.read_bytes() == original


def test_report_survives_vote_failure(deploy, market, monkeypatch, tmp_path):
    _, report = market
    path = tmp_path / "failed-vote.json"

    def fail_vote(*args):
        saved = json.loads(path.read_text())
        assert args[:4] == tuple(
            saved[key] for key in ("configurator", "controller", "gauge", "lm_callback")
        )
        assert boa.env.get_code(saved["price_oracle"])
        assert saved["activation_vote_id"] is None
        raise RuntimeError("vote failed")

    monkeypatch.setattr(deploy, "_create_activation_vote", fail_vote)
    with boa.env.anchor(), pytest.raises(RuntimeError, match="vote failed"):
        deploy._deploy(report["deployer"], True, path, FACTORY_REPORT, True, None, None)
    assert json.loads(path.read_text())["params"]["fee"] == deploy.FEE


def test_activation_borrow_repay(deploy, market, tmp_path):
    _, unactivated = market
    api_key = os.environ.get("ETHERSCAN_API_KEY") or os.environ.get("EXPLORER_TOKEN")
    assert api_key, "Set ETHERSCAN_API_KEY or EXPLORER_TOKEN"
    with boa.env.anchor():
        path = tmp_path / "activated.json"
        deploy._deploy(
            unactivated["deployer"], True, path, FACTORY_REPORT, True, api_key, None
        )
        report = json.loads(path.read_text())
        controller = boa.load_partial(deploy.LEND_CONTROLLER).at(report["controller"])
        vault = boa.load_partial("curve_stablecoin/lending/Vault.vy").at(
            report["vault"]
        )
        callback = boa.load_partial(deploy.LM_CALLBACK_SRC).at(report["lm_callback"])
        amm = boa.load_partial(deploy.AMM_SRC).at(report["amm"])
        assert report["activation_vote_id"] >= 0
        assert report["callback_attached"]
        assert (
            report["params"]["borrow_cap"] == controller.borrow_cap() == 3_000_000 * WAD
        )
        assert (
            report["params"]["admin_fee"] == controller.admin_percentage() == WAD // 10
        )
        assert amm.liquidity_mining_callback() == callback.address
        gauges = boa.from_etherscan(deploy.GAUGE_CONTROLLER, api_key=api_key)
        for gauge in [report["gauge"], callback.address]:
            assert gauges.gauge_types(gauge) == 0
            assert gauges.get_gauge_weight(gauge) == 0

        token = boa.loads_abi(
            json.dumps(build_abi_output(ERC20_MOCK_DEPLOYER.compiler_data))
        )
        collateral = token.at(deploy.LP_POOL)
        borrowed = token.at(deploy.CRVUSD)
        depositor = boa.env.generate_address("depositor")
        borrower = boa.env.generate_address("borrower")
        boa.deal(borrowed, depositor, 90_000 * WAD)
        borrowed.approve(vault, 2**256 - 1, sender=depositor)
        vault.deposit(90_000 * WAD, sender=depositor)
        boa.deal(collateral, borrower, 100_000 * WAD, adjust_supply=False)
        collateral.approve(controller, 2**256 - 1, sender=borrower)
        controller.create_loan(100_000 * WAD, 90_000 * WAD, 4, sender=borrower)
        mp = boa.load_partial(deploy.HYPERBOLIC_MP).at(report["monetary_policy"])
        assert abs(mp.rate() * (365 * 86400) / WAD - 0.25) < 1e-8
        assert callback.user_collateral(borrower) > 0
        boa.env.time_travel(seconds=3600)
        assert controller.debt(borrower) > 90_000 * WAD
        boa.deal(borrowed, borrower, 100_000 * WAD)
        borrowed.approve(controller, 2**256 - 1, sender=borrower)
        controller.repay(controller.debt(borrower), sender=borrower)
        assert not controller.loan_exists(borrower)
        assert callback.user_collateral(borrower) == 0
