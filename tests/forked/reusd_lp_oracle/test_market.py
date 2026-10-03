import importlib.util
import json
from pathlib import Path

import boa
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
