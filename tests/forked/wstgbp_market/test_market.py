import importlib.util
import json
from pathlib import Path

import boa
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

        oracle = boa.load_partial_solc(deploy.WSTGBP_FX_ORACLE).at(
            report["price_oracle"]
        )
        fx_ema = boa.load_partial_solc(deploy.CHAINLINK_EMA).at(report["fx_ema"])
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
        assert amm.A() == deploy.A == 180
        assert amm.fee() == deploy.FEE == 6 * 10**15
        assert controller.loan_discount() == deploy.LOAN_DISCOUNT == 43 * 10**15
        assert (
            controller.liquidation_discount()
            == deploy.LIQUIDATION_DISCOUNT
            == 23 * 10**15
        )
        assert controller.borrow_cap() == 0
        assert controller.admin_percentage() == 0
        assert int(str(amm.liquidity_mining_callback()), 16) == 0
        assert policy.CONTROLLER() == controller.address
        assert 499 * 10**14 < policy.target_apr() <= 5 * 10**16

        original = path.read_bytes()
        with pytest.raises(SystemExit, match="already exists"):
            deploy._deploy(report["deployer"], True, path, FACTORY_REPORT)
        assert path.read_bytes() == original
