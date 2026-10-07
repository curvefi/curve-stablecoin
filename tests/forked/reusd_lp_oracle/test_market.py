import importlib.util
import json
import os
from pathlib import Path

import boa
import curve_dao
import pytest

from tests.forked.settings import WEB3_PROVIDER_URL


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
        deploy._deploy(report["deployer"], True, path, Path())
    assert path.read_bytes() == original


def test_admin_deployment_keeps_initial_settings(deploy, market, tmp_path):
    _, report = market
    factory = boa.load_partial(deploy.LEND_FACTORY).at(report["factory"])
    with boa.env.anchor():
        path = tmp_path / "admin-deployment.json"
        deploy._deploy(str(factory.admin()), True, path, FACTORY_REPORT)
        saved = json.loads(path.read_text())
        controller = boa.load_partial(deploy.LEND_CONTROLLER).at(saved["controller"])
        amm = boa.load_partial(deploy.AMM_SRC).at(saved["amm"])
        assert saved["params"]["borrow_cap"] == controller.borrow_cap() == 0
        assert saved["params"]["admin_fee"] == controller.admin_percentage() == 0
        assert int(str(amm.liquidity_mining_callback()), 16) == 0
        assert not saved["callback_attached"]
        assert "activation_vote_id" not in saved


@pytest.fixture(scope="module")
def api_key():
    key = os.environ.get("ETHERSCAN_API_KEY") or os.environ.get("EXPLORER_TOKEN")
    assert key, "Set ETHERSCAN_API_KEY or EXPLORER_TOKEN"
    return key


@pytest.fixture
def proposer(deploy, market, api_key):
    with boa.env.anchor():
        dao = curve_dao.get_dao_parameters(deploy.VOTE_DAO)
        vecrv = boa.from_etherscan(dao["token"], api_key=api_key)
        crv = boa.from_etherscan(vecrv.token(), api_key=api_key)
        proposer = boa.env.generate_address("activation-proposer")
        boa.env.eoa = proposer
        amount = 10_000 * WAD
        boa.deal(crv, proposer, amount)
        crv.approve(vecrv, amount)
        vecrv.create_lock(amount, boa.env.evm.patch.timestamp + 4 * 365 * 86400)
        boa.env.time_travel(blocks=1)
        yield proposer


def test_deployer_proposes_activation(deploy, proposer, api_key, tmp_path):
    path = tmp_path / "activation.json"
    deploy._deploy(proposer, True, path, FACTORY_REPORT, True, api_key)
    report = json.loads(path.read_text())
    vote_id = report["activation_vote_id"]
    dao = curve_dao.get_dao_parameters(deploy.VOTE_DAO)
    voting = boa.env.lookup_contract(dao["voting"])
    event = next(log for log in voting.get_logs() if type(log).__name__ == "StartVote")
    assert event.voteId == vote_id
    assert event.creator == report["deployer"] == proposer
    assert boa.env.get_code(proposer) == b""

    controller = boa.load_partial(deploy.LEND_CONTROLLER).at(report["controller"])
    amm = boa.load_partial(deploy.AMM_SRC).at(report["amm"])
    gauges = boa.from_etherscan(deploy.GAUGE_CONTROLLER, api_key=api_key)
    # Creating the proposal alone must leave the market inactive.
    assert controller.borrow_cap() == report["params"]["borrow_cap"] == 0
    assert controller.admin_percentage() == report["params"]["admin_fee"] == 0
    assert int(str(amm.liquidity_mining_callback()), 16) == 0
    assert not report["callback_attached"]
    for gauge in (report["gauge"], report["lm_callback"]):
        with boa.reverts():
            gauges.gauge_types(gauge)

    # Only the test passes and executes the vote, entirely on the fork.
    curve_dao.simulate(vote_id, deploy.VOTE_DAO, api_key)
    assert controller.borrow_cap() == deploy.BORROW_CAP
    assert controller.admin_percentage() == deploy.ADMIN_FEE
    assert amm.liquidity_mining_callback() == report["lm_callback"]
    for gauge in (report["gauge"], report["lm_callback"]):
        assert gauges.gauge_types(gauge) == 0
        assert gauges.get_gauge_weight(gauge) == 0


def test_ineligible_proposer_fails_before_deployment(deploy, market, api_key, tmp_path):
    _, report = market
    with boa.env.anchor():
        factory = boa.load_partial(deploy.LEND_FACTORY).at(report["factory"])
        count = factory.market_count()
        nonce = deploy._factory_nonce(factory.address)
        path = tmp_path / "ineligible.json"
        with pytest.raises(AssertionError, match="Deployer is not eligible"):
            deploy._deploy(
                boa.env.generate_address("ineligible"),
                True,
                path,
                FACTORY_REPORT,
                True,
                api_key,
            )
        assert not path.exists()
        assert factory.market_count() == count
        assert deploy._factory_nonce(factory.address) == nonce


def test_failed_proposal_preserves_report(
    deploy, proposer, api_key, tmp_path, monkeypatch
):
    path = tmp_path / "failed-vote.json"
    saved = []

    def fail_vote(*args, **kwargs):
        saved.append(path.read_bytes())
        raise RuntimeError("Proposal failed")

    monkeypatch.setattr(curve_dao, "create_vote", fail_vote)
    with pytest.raises(RuntimeError, match="Proposal failed"):
        deploy._deploy(proposer, True, path, FACTORY_REPORT, True, api_key)
    assert path.read_bytes() == saved[0]
    report = json.loads(path.read_text())
    assert report["deployer"] == proposer
    assert "activation_vote_id" not in report
    for key in ("vault", "controller", "amm", "gauge", "lm_callback"):
        assert boa.env.get_code(report[key])
