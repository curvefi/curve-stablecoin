import importlib.util
import json
import os
from pathlib import Path

import boa
import curve_dao
import pytest

from tests.forked.settings import WEB3_PROVIDER_URL


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deploy/llamalend/ethereum/markets/wstGBP-crvUSD/deploy.py"
FACTORY_REPORT = ROOT / "deployments/llamalend/ethereum/factory.jsonc"
BLOCK = 26_296_149
WAD = 10**18


def test_wstgbp_market_deployment(tmp_path):
    assert WEB3_PROVIDER_URL, "Set WEB3_PROVIDER_URL"
    spec = importlib.util.spec_from_file_location("wstgbp_deploy", SCRIPT)
    deploy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deploy)

    with boa.fork(WEB3_PROVIDER_URL, block_identifier=BLOCK, allow_dirty=True):
        path = tmp_path / "wstgbp.json"
        deploy._deploy(boa.env.generate_address("deployer"), True, path, FACTORY_REPORT)
        report = json.loads(path.read_text())

        oracle = boa.load_partial(deploy.WSTGBP_FX_ORACLE).at(report["price_oracle"])
        fx_ema = boa.load_partial(deploy.CHAINLINK_EMA).at(report["fx_ema"])
        wrapper = boa.loads_abi(
            '[{"name":"burncost","inputs":[],"outputs":[{"type":"uint256"}],'
            '"stateMutability":"view","type":"function"}]'
        ).at(deploy.WSTGBP)
        controller = boa.load_partial(deploy.LEND_CONTROLLER).at(report["controller"])
        amm = boa.load_partial(deploy.AMM_SRC).at(report["amm"])
        policy = boa.load_partial(deploy.HYPERBOLIC_MP).at(report["monetary_policy"])

        assert fx_ema.OBSERVATIONS() == deploy.OBSERVATIONS == 20
        assert fx_ema.INTERVAL() == deploy.INTERVAL == 30
        assert oracle.MAX_FX_AGE() == 30 * 3600
        assert oracle.MAX_UPSIDE_SPEED() == 28_935_185_185
        assert oracle.cachedQuote() == wrapper.burncost()
        expected = wrapper.burncost() * fx_ema.price() // WAD
        assert oracle.price() == oracle.price_w() == expected
        assert oracle.price() == expected
        assert not oracle.frozen()
        assert amm.price_oracle_contract() == oracle.address
        assert amm.A() == deploy.A == 150
        assert amm.fee() == deploy.FEE == 4 * 10**15
        assert controller.loan_discount() == deploy.LOAN_DISCOUNT == 41 * 10**15
        assert (
            controller.liquidation_discount()
            == deploy.LIQUIDATION_DISCOUNT
            == 21 * 10**15
        )
        assert controller.borrow_cap() == 0
        assert controller.admin_percentage() == 0
        assert int(str(amm.liquidity_mining_callback()), 16) == 0
        assert policy.CONTROLLER() == controller.address
        params = policy.parameters()
        assert (
            params.target_utilization,
            params.target_rate,
            params.low_ratio,
            params.high_ratio,
            params.rate_shift,
        ) == (90 * 10**16, 5 * 10**16 // (365 * 86400), 5 * 10**17, 5 * 10**18, 0)
        lender_vault = boa.load_vyi("curve_stablecoin/interfaces/IVault.vyi").at(
            report["vault"]
        )
        assert lender_vault.maxSupply() == deploy.SUPPLY_LIMIT == 2**256 - 1
        assert not report["callback_attached"]
        assert "activation_vote_id" not in report
        assert 499 * 10**14 < policy.target_apr() <= 5 * 10**16

        original = path.read_bytes()
        with pytest.raises(SystemExit, match="already exists"):
            deploy._deploy(report["deployer"], True, path, FACTORY_REPORT)
        assert path.read_bytes() == original


@pytest.fixture(scope="module")
def deploy():
    spec = importlib.util.spec_from_file_location("market_deploy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def governance_fork():
    assert WEB3_PROVIDER_URL, "Set WEB3_PROVIDER_URL"
    with boa.fork(WEB3_PROVIDER_URL, block_identifier=BLOCK, allow_dirty=True):
        yield


@pytest.fixture(scope="module")
def api_key():
    key = (
        os.getenv("ETHERSCAN_KEY")
        or os.getenv("ETHERSCAN_API_KEY")
        or os.getenv("EXPLORER_TOKEN")
    )
    assert key, "Set ETHERSCAN_KEY, ETHERSCAN_API_KEY or EXPLORER_TOKEN"
    return key


@pytest.fixture
def proposer(deploy, governance_fork, api_key):
    with boa.env.anchor():
        dao = curve_dao.get_dao_parameters(deploy.VOTE_DAO)
        vecrv = boa.from_etherscan(dao["token"], api_key=api_key)
        crv = boa.from_etherscan(vecrv.token(), api_key=api_key)
        address = boa.env.generate_address("activation-proposer")
        boa.env.eoa = address
        amount = 10_000 * WAD
        boa.deal(crv, address, amount)
        crv.approve(vecrv, amount)
        vecrv.create_lock(amount, boa.env.timestamp + 4 * 365 * 86400)
        boa.env.time_travel(blocks=1)
        yield address


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
    assert controller.borrow_cap() == report["params"]["borrow_cap"] == 0
    assert controller.admin_percentage() == report["params"]["admin_fee"] == 0
    assert int(str(amm.liquidity_mining_callback()), 16) == 0
    assert not report["callback_attached"]
    for gauge in (report["gauge"], report["lm_callback"]):
        with boa.reverts():
            gauges.gauge_types(gauge)

    # Passage and execution happen only on the fork.
    curve_dao.simulate(vote_id, deploy.VOTE_DAO, api_key)
    assert controller.borrow_cap() == deploy.BORROW_CAP == 80_000 * WAD
    assert controller.admin_percentage() == deploy.ADMIN_FEE == 10**17
    assert amm.liquidity_mining_callback() == report["lm_callback"]
    for gauge in (report["gauge"], report["lm_callback"]):
        assert gauges.gauge_types(gauge) == 0
        assert gauges.get_gauge_weight(gauge) == 0


def test_ineligible_proposer_fails_before_deployment(
    deploy, governance_fork, api_key, tmp_path
):
    with boa.env.anchor():
        contracts = json.loads(FACTORY_REPORT.read_text())["contracts"]
        factory = boa.load_partial(deploy.LEND_FACTORY).at(contracts["factory"])
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


def test_admin_deployment_keeps_initial_settings(deploy, governance_fork, tmp_path):
    with boa.env.anchor():
        contracts = json.loads(FACTORY_REPORT.read_text())["contracts"]
        factory = boa.load_partial(deploy.LEND_FACTORY).at(contracts["factory"])
        path = tmp_path / "admin-deployment.json"
        deploy._deploy(str(factory.admin()), True, path, FACTORY_REPORT)
        report = json.loads(path.read_text())
        controller = boa.load_partial(deploy.LEND_CONTROLLER).at(report["controller"])
        amm = boa.load_partial(deploy.AMM_SRC).at(report["amm"])
        assert controller.borrow_cap() == report["params"]["borrow_cap"] == 0
        assert controller.admin_percentage() == report["params"]["admin_fee"] == 0
        assert int(str(amm.liquidity_mining_callback()), 16) == 0
        assert not report["callback_attached"]
        assert "activation_vote_id" not in report


@pytest.mark.parametrize(
    "has_api_key, error", [(False, "etherscan-api-key"), (True, "pinata-token")]
)
def test_create_vote_requires_credentials(deploy, monkeypatch, has_api_key, error):
    for name in ("ETHERSCAN_API_KEY", "ETHERSCAN_KEY", "PINATA_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    args = [
        "deploy.py",
        "--create-vote",
        "--account-name",
        "unused",
        "--rpc-url",
        "unused",
        "--factory-deployment",
        str(FACTORY_REPORT),
    ]
    if has_api_key:
        args += ["--etherscan-api-key", "test-api-key"]
    monkeypatch.setattr("sys.argv", args)
    with pytest.raises(SystemExit, match=error):
        deploy.main()
