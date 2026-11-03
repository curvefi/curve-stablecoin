import importlib.util
import json
from pathlib import Path

import boa
import pytest

from tests.forked.settings import WEB3_PROVIDER_URL
from tests.unitary.price_oracles.chainlink_price_oracle.test_oracle import FEED_DEPLOYER


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
        wousd_oracle = boa.load_partial(deploy.ERC4626_EMA_WRAPPER).at(
            report["wousd_oracle"]
        )
        usdc_oracle = boa.load_partial(deploy.CHAINLINK_PRICE_ORACLE).at(
            report["usdc_oracle"]
        )
        oracle = boa.load_partial(deploy.CHAIN_ORACLE).at(report["price_oracle"])
        feed = boa.loads_abi(
            '[{"name":"latestRoundData","inputs":[],"outputs":'
            '[{"type":"uint80"},{"type":"int256"},{"type":"uint256"},'
            '{"type":"uint256"},{"type":"uint80"}],'
            '"stateMutability":"view","type":"function"}]'
        ).at(deploy.USDC_USD_FEED)
        controller = boa.load_partial(deploy.LEND_CONTROLLER).at(report["controller"])
        amm = boa.load_partial(deploy.AMM_SRC).at(report["amm"])
        policy = boa.load_partial(deploy.HYPERBOLIC_MP).at(report["monetary_policy"])
        pool = boa.loads_abi(
            '[{"name":"coins","inputs":[{"type":"uint256"}],'
            '"outputs":[{"type":"address"}],"stateMutability":"view",'
            '"type":"function"},'
            '{"name":"price_oracle","inputs":[{"type":"uint256"}],'
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
        assert (
            str(pool.coins(0)).lower() == "0x2a8e1e676ec238d8a992307b495b45b3feaa5e86"
        )
        assert (
            str(pool.coins(1)).lower() == "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
        )
        assert pool.ma_exp_time() == 866
        assert pool_oracle.BORROWED_IXS(0) == 1
        assert pool_oracle.COLLATERAL_IXS(0) == 0
        assert pool_oracle.price() == WAD * WAD // pool.price_oracle(0)
        assert wousd_oracle.ORACLE() == pool_oracle.address
        assert wousd_oracle.VAULT() == deploy.WOUSD
        assert usdc_oracle.FEED() == deploy.USDC_USD_FEED
        assert usdc_oracle.MAX_AGE() == deploy.USDC_MAX_AGE == 86400
        assert usdc_oracle.price() == feed.latestRoundData()[1] * 10**10
        assert oracle.ORACLE_COUNT() == 2
        assert oracle.ORACLES(0) == wousd_oracle.address
        assert oracle.ORACLES(1) == usdc_oracle.address
        assert oracle.price() == oracle.price_w()
        wousd_usdc = pool_oracle.price() * vault.convertToAssets(WAD) // WAD
        assert wousd_oracle.price() == wousd_usdc
        assert oracle.price() == wousd_usdc * usdc_oracle.price() // WAD
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

        # Keep the real pool and vault, varying only the Chainlink price feed.
        mock_feed = FEED_DEPLOYER.deploy(8, override_address=deploy.USDC_USD_FEED)
        for answer in [87_000_000, 100_000_000, 101_000_000]:
            mock_feed.set_round(answer, boa.env.timestamp)
            expected = wousd_usdc * answer * 10**10 // WAD
            assert oracle.price() == oracle.price_w() == expected

        mock_feed.set_fail(True)
        for entrypoint in (oracle.price, oracle.price_w):
            with boa.reverts("Feed unavailable"):
                entrypoint()
        mock_feed.set_fail(False)
        boa.env.time_travel(seconds=deploy.USDC_MAX_AGE + 1)
        for entrypoint in (oracle.price, oracle.price_w):
            with boa.reverts("Stale price"):
                entrypoint()
