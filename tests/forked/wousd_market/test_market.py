import importlib.util
import json
from pathlib import Path

import boa
import pytest

from tests.forked.settings import WEB3_PROVIDER_URL


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/deploy/llamalend/ethereum/markets/wOUSD-crvUSD/deploy.py"
FACTORY_REPORT = ROOT / "deployments/llamalend/ethereum/factory.jsonc"
BLOCK = 26_296_149
WAD = 10**18


def test_wousd_market_deployment(tmp_path):
    assert WEB3_PROVIDER_URL, "Set WEB3_PROVIDER_URL"
    spec = importlib.util.spec_from_file_location("wousd_deploy", SCRIPT)
    deploy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deploy)

    with boa.fork(WEB3_PROVIDER_URL, block_identifier=BLOCK, allow_dirty=True):
        path = tmp_path / "wousd.json"
        deploy._deploy(boa.env.generate_address("deployer"), True, path, FACTORY_REPORT)
        report = json.loads(path.read_text())

        pool_oracle = boa.load_partial(deploy.ORACLE_FROM_CURVE_POOLS).at(
            report["pool_oracle"]
        )
        oracle = boa.load_partial(deploy.ERC4626_EMA_WRAPPER).at(report["price_oracle"])
        controller = boa.load_partial(deploy.LEND_CONTROLLER).at(report["controller"])
        amm = boa.load_partial(deploy.AMM_SRC).at(report["amm"])
        policy = boa.load_partial(deploy.HYPERBOLIC_MP).at(report["monetary_policy"])
        pool = boa.loads_abi(
            '[{"name":"price_oracle","inputs":[{"type":"uint256"}],'
            '"outputs":[{"type":"uint256"}],"stateMutability":"view",'
            '"type":"function"},'
            '{"name":"ma_exp_time","inputs":[],"outputs":[{"type":"uint256"}],'
            '"stateMutability":"view","type":"function"}]'
        ).at(deploy.POOL)
        vault = boa.loads_abi(
            '[{"name":"convertToAssets","inputs":[{"type":"uint256"}],'
            '"outputs":[{"type":"uint256"}],"stateMutability":"view",'
            '"type":"function"}]'
        ).at(deploy.WOUSD)

        assert pool_oracle.POOLS(0) == deploy.POOL
        assert pool.ma_exp_time() == 866
        assert pool_oracle.BORROWED_IXS(0) == 1
        assert pool_oracle.COLLATERAL_IXS(0) == 0
        assert pool_oracle.price() == WAD * WAD // pool.price_oracle(0)
        assert oracle.ORACLE() == pool_oracle.address
        assert oracle.VAULT() == deploy.WOUSD
        assert oracle.price() == oracle.price_w()
        assert oracle.price() == pool_oracle.price() * vault.convertToAssets(WAD) // WAD
        assert amm.price_oracle_contract() == oracle.address
        assert amm.A() == deploy.A == 772
        assert amm.fee() == deploy.FEE == 39 * 10**14
        assert controller.loan_discount() == deploy.LOAN_DISCOUNT == 13 * 10**15
        assert (
            controller.liquidation_discount()
            == deploy.LIQUIDATION_DISCOUNT
            == 8 * 10**15
        )
        assert controller.borrow_cap() == 0
        assert controller.admin_percentage() == 0
        assert int(str(amm.liquidity_mining_callback()), 16) == 0
        assert policy.CONTROLLER() == controller.address
        assert 499 * 10**14 < policy.target_apr() <= 5 * 10**16
        assert report["params"]["initial_price"] > 0

        original = path.read_bytes()
        with pytest.raises(SystemExit, match="already exists"):
            deploy._deploy(report["deployer"], True, path, FACTORY_REPORT)
        assert path.read_bytes() == original
