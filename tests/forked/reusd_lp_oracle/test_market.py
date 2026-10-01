import importlib.util
import json
import os
from pathlib import Path

import boa
import cbor2
import pytest
from vyper.compiler.output import build_abi_output
from vyper.compiler.settings import OptimizationLevel

from tests.forked.settings import WEB3_PROVIDER_URL
from tests.utils.deployers import ERC20_MOCK_DEPLOYER


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = (
    ROOT / "scripts/deploy/llamalend/ethereum/markets/reUSDsfrxUSDLP-crvUSD/deploy.py"
)
WAD = 10**18


@pytest.fixture(scope="module")
def deploy():
    spec = importlib.util.spec_from_file_location("reusd_lp_deploy", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module", params=[26_093_879, "latest"])
def market(request, deploy, tmp_path_factory):
    assert WEB3_PROVIDER_URL, "Set WEB3_PROVIDER_URL"
    with boa.fork(WEB3_PROVIDER_URL, block_identifier=request.param, allow_dirty=True):
        path = tmp_path_factory.mktemp("reusd") / "deployment.json"
        deploy._deploy(
            boa.env.generate_address("deployer"),
            True,
            path,
            ROOT / "deployments/llamalend/ethereum/factory.jsonc",
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
        assert report["params"]["reusd_feed"] == adapter.REUSD_FEED()
        assert 0 < adapter.price() <= WAD
        composed = (lp.price() * adapter.price() // WAD) * agg.price() // WAD
        assert oracle.price() == oracle.price_w() == composed == amm.price_oracle()
        assert amm.coins(0) == deploy.CRVUSD and amm.coins(1) == deploy.LP_POOL
        assert amm.A() == 440
        assert amm.fee() == deploy.FEE <= 4 * WAD // 440
        assert controller.loan_discount() == 3 * 10**16
        assert controller.liquidation_discount() == 25 * 10**15
        assert controller.configurator() == report["configurator"]
        assert mp.CONTROLLER() == controller.address
        assert controller.borrow_cap() == 0
        assert int(str(amm.liquidity_mining_callback()), 16) == 0
        assert callback.factory() == deploy.LM_CALLBACK_FACTORY
        assert callback.AMM() == amm.address
        assert callback.version() == lm_factory.version() == "1.0.0"
        assert (
            lm_factory.get_blueprint_by_lm_callback(callback)
            == deploy.LM_CALLBACK_BLUEPRINT
        )
        assert boa.env.get_code(deploy.LM_CALLBACK_BLUEPRINT) == (
            b"\xfe\x71\x00"
            + boa.load_partial(deploy.LM_CALLBACK_SRC).compiler_data.bytecode
        )


def test_report_cannot_be_overwritten(deploy, market):
    path, report = market
    original = path.read_bytes()
    with pytest.raises(SystemExit, match="already exists"):
        deploy._deploy(report["deployer"], True, path, Path(), False, None, None)
    assert path.read_bytes() == original


def test_factory_blueprints(deploy, market):
    _, report = market
    factory = boa.load_partial(deploy.LEND_FACTORY).at(report["factory"])
    for key, source, optimize in [
        ("amm_blueprint", deploy.AMM_SRC, OptimizationLevel.CODESIZE),
        ("controller_blueprint", deploy.LEND_CONTROLLER, OptimizationLevel.CODESIZE),
        (
            "vault_blueprint",
            "curve_stablecoin/lending/Vault.vy",
            OptimizationLevel.CODESIZE,
        ),
        (
            "controller_view_blueprint",
            "curve_stablecoin/lending/LendControllerView.vy",
            OptimizationLevel.CODESIZE,
        ),
    ]:
        compiled = boa.load_partial(source, compiler_args={"optimize": optimize})
        actual = boa.env.get_code(getattr(factory, key)())
        expected = b"\xfe\x71\x00" + compiled.compiler_data.bytecode
        actual_size = int.from_bytes(actual[-2:], "big")
        expected_size = int.from_bytes(expected[-2:], "big")
        assert actual[:-actual_size] == expected[:-expected_size]
        # Only the source-integrity hash may differ; executable code and the
        # remaining compiler metadata (including immutable sizes) must match.
        assert (
            cbor2.loads(actual[-actual_size:-2])[1:]
            == cbor2.loads(expected[-expected_size:-2])[1:]
        )


def test_live_redemption_floor(deploy, market):
    _, report = market
    with boa.env.anchor():
        adapter = boa.load_partial(deploy.REUSD_ADAPTER).at(report["reusd_adapter"])
        registry = boa.loads_abi(
            '[{"name":"redemptionHandler","inputs":[],"outputs":[{"type":"address"}],'
            '"stateMutability":"view","type":"function"}]'
        ).at("0x10101010E0C3171D894B71B3400668aF311e7D94")
        handler = boa.loads_abi(
            '[{"name":"baseRedemptionFee","inputs":[],"outputs":[{"type":"uint256"}],'
            '"stateMutability":"view","type":"function"}]'
        ).at(registry.redemptionHandler())
        floor = WAD - handler.baseRedemptionFee()
        pool = boa.loads(
            """
# pragma version 0.4.3
value: public(uint256)
@external
def set_value(_value: uint256):
    self.value = _value
@external
@view
def price_oracle(i: uint256) -> uint256:
    return 10**36 // self.value
""",
            override_address="0xc522A6606BBA746d7960404F22a3DB936B6F4F50",
        )
        for market_price in [101 * WAD // 100, WAD, 99 * WAD // 100, WAD // 2]:
            pool.set_value(market_price)
            expected = min(WAD, max(10**36 // (10**36 // market_price), floor))
            assert adapter.price() == adapter.price_w() == expected
        assert adapter.price() > WAD // 2  # The floor is not an executable exit quote.


def test_live_exit_quotes(deploy, market):
    path, report = market
    pool = boa.loads_abi(
        '[{"name":"calc_withdraw_one_coin","inputs":[{"type":"uint256"},{"type":"int128"}],'
        '"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"}]'
    ).at(deploy.LP_POOL)
    bridge = boa.loads_abi(
        '[{"name":"get_dy","inputs":[{"type":"int128"},{"type":"int128"},{"type":"uint256"}],'
        '"outputs":[{"type":"uint256"}],"stateMutability":"view","type":"function"},'
        '{"name":"coins","inputs":[{"type":"uint256"}],"outputs":[{"type":"address"}],'
        '"stateMutability":"view","type":"function"}]'
    ).at("0xc522A6606BBA746d7960404F22a3DB936B6F4F50")
    scrvusd = boa.loads_abi(
        '[{"name":"convertToAssets","inputs":[{"type":"uint256"}],"outputs":[{"type":"uint256"}],'
        '"stateMutability":"view","type":"function"}]'
    ).at(bridge.coins(1))
    oracle = boa.load_partial(deploy.CHAIN_ORACLE).at(report["price_oracle"])
    rows = []
    for size in [10_000, 100_000, 1_000_000, 3_000_000]:
        lp_amount = size * WAD
        reusd = pool.calc_withdraw_one_coin(lp_amount, 0)
        exit_crvusd = scrvusd.convertToAssets(bridge.get_dy(0, 1, reusd))
        assert exit_crvusd > 0
        rows.append(
            dict(
                lp_tokens=size,
                exit_crvusd=exit_crvusd,
                oracle_usd=oracle.price() * size,
            )
        )
    path.with_name("exit-quotes.json").write_text(json.dumps(rows, indent=2))


def test_nonce_race_preserves_partial_report(deploy, market, monkeypatch, tmp_path):
    _, report = market
    with boa.env.anchor():
        factory = boa.load_partial(deploy.LEND_FACTORY).at(report["factory"])
        policy = boa.load(
            "curve_stablecoin/testing/ConstantMonetaryPolicyLending.vy",
            deploy.CRVUSD,
            10**9,
            10**9,
        )
        count = factory.market_count()
        predict = deploy._predict_controller
        calls = 0

        def interleave(address):
            nonlocal calls
            calls += 1
            if calls == 2:
                factory.create(
                    deploy.CRVUSD,
                    deploy.LP_POOL,
                    deploy.A,
                    deploy.FEE,
                    deploy.LOAN_DISCOUNT,
                    deploy.LIQUIDATION_DISCOUNT,
                    report["price_oracle"],
                    policy,
                    deploy.SUPPLY_LIMIT,
                )
            return predict(address)

        monkeypatch.setattr(deploy, "_predict_controller", interleave)
        path = tmp_path / "interrupted.json"
        with pytest.raises(AssertionError, match="Factory nonce changed"):
            deploy._deploy(
                report["deployer"],
                True,
                path,
                ROOT / "deployments/llamalend/ethereum/factory.jsonc",
                False,
                None,
                None,
            )
        partial = json.loads(path.read_text())
        assert partial["complete"] is False
        assert boa.env.get_code(partial["monetary_policy"])
        assert "vault" not in partial
        assert factory.market_count() == count + 1
        # A nonce race after the script's check also fails inside factory.create().
        with boa.reverts("Controller only"):
            factory.create(
                deploy.CRVUSD,
                deploy.LP_POOL,
                deploy.A,
                deploy.FEE,
                deploy.LOAN_DISCOUNT,
                deploy.LIQUIDATION_DISCOUNT,
                partial["price_oracle"],
                partial["monetary_policy"],
                deploy.SUPPLY_LIMIT,
            )
        assert factory.market_count() == count + 1


@pytest.mark.parametrize("fault", ["old_callback_factory", "wrong_chain", "wrong_pool"])
def test_preflight_before_deployment(deploy, market, monkeypatch, tmp_path, fault):
    _, report = market
    with boa.env.anchor():
        if fault == "old_callback_factory":
            monkeypatch.setattr(
                deploy,
                "LM_CALLBACK_FACTORY",
                "0x323E4BA335F830B6bd3bDeD522368b2A8e3a880E",
            )
        elif fault == "wrong_chain":
            boa.env.evm.patch.chain_id = 10
        else:
            monkeypatch.setattr(deploy, "LP_POOL_COINS", {0: deploy.CRVUSD})
        path = tmp_path / "invalid.json"
        with pytest.raises((AssertionError, boa.BoaError)):
            deploy._deploy(
                report["deployer"],
                True,
                path,
                ROOT / "deployments/llamalend/ethereum/factory.jsonc",
                False,
                None,
                None,
            )
        assert not path.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("complete", False),
        ("activation_vote_pending", True),
        ("activation_vote_id", 123),
    ],
)
def test_activation_rejects_incomplete_or_repeated_vote(
    deploy, market, tmp_path, field, value
):
    _, report = market
    path = tmp_path / "invalid-vote.json"
    path.write_text(json.dumps(dict(report, **{field: value})))
    with pytest.raises(AssertionError):
        deploy._activate(path, True, None, None)


def test_activation_and_lifecycle(deploy, market):
    path, report = market
    api_key = os.environ.get("ETHERSCAN_API_KEY") or os.environ.get("EXPLORER_TOKEN")
    assert api_key, "Set ETHERSCAN_API_KEY or EXPLORER_TOKEN"
    original = path.read_bytes()
    with boa.env.anchor():
        controller = boa.load_partial(deploy.LEND_CONTROLLER).at(report["controller"])
        vault = boa.load_partial("curve_stablecoin/lending/Vault.vy").at(
            report["vault"]
        )
        callback = boa.load_partial(deploy.LM_CALLBACK_SRC).at(report["lm_callback"])
        amm = boa.load_partial(deploy.AMM_SRC).at(report["amm"])
        mp = boa.load_partial(deploy.HYPERBOLIC_MP).at(report["monetary_policy"])
        token = boa.loads_abi(
            json.dumps(build_abi_output(ERC20_MOCK_DEPLOYER.compiler_data))
        )
        collateral = token.at(deploy.LP_POOL)
        borrowed = token.at(deploy.CRVUSD)
        depositor = boa.env.generate_address("depositor")
        borrower = boa.env.generate_address("borrower")
        liquidator = boa.env.generate_address("liquidator")
        boa.deal(borrowed, depositor, deploy.BORROW_CAP)
        borrowed.approve(vault, 2**256 - 1, sender=depositor)
        vault.deposit(deploy.BORROW_CAP, sender=depositor)
        boa.deal(collateral, borrower, 100_000 * WAD, adjust_supply=False)
        collateral.approve(controller, 2**256 - 1, sender=borrower)
        with boa.reverts("Borrow cap exceeded"):
            controller.create_loan(100_000 * WAD, 90_000 * WAD, 4, sender=borrower)

        vote_id = deploy._activate(path, True, api_key, None)
        assert vote_id >= 0
        assert path.read_bytes() == original
        assert controller.borrow_cap() == deploy.BORROW_CAP
        assert controller.admin_percentage() == deploy.ADMIN_FEE
        assert amm.liquidity_mining_callback() == callback.address
        gauges = boa.from_etherscan(deploy.GAUGE_CONTROLLER, api_key=api_key)
        assert gauges.gauge_types(report["gauge"]) == 0
        assert gauges.gauge_types(callback.address) == 0
        assert gauges.get_gauge_weight(report["gauge"]) == 0
        assert gauges.get_gauge_weight(callback.address) == 0
        for utilization, apr in [(0, 0.025), (90, 0.05), (100, 0.25)]:
            rate = mp.future_rate(0, deploy.BORROW_CAP * utilization // 100)
            assert abs(rate * (365 * 86400) / WAD - apr) < 1e-8

        gauge = boa.loads_abi(
            json.dumps(
                [
                    dict(
                        name="deposit",
                        type="function",
                        stateMutability="nonpayable",
                        inputs=[dict(type="uint256")],
                        outputs=[],
                    ),
                    dict(
                        name="withdraw",
                        type="function",
                        stateMutability="nonpayable",
                        inputs=[dict(type="uint256")],
                        outputs=[],
                    ),
                    dict(
                        name="balanceOf",
                        type="function",
                        stateMutability="view",
                        inputs=[dict(type="address")],
                        outputs=[dict(type="uint256")],
                    ),
                ]
            )
        ).at(report["gauge"])
        vault.approve(gauge, 2**256 - 1, sender=depositor)
        gauge.deposit(1000 * WAD, sender=depositor)
        assert gauge.balanceOf(depositor) == 1000 * WAD
        # Borrow all remaining liquidity to exercise the selected 25% upper rate.
        vault.withdraw(deploy.BORROW_CAP - 90_000 * WAD, sender=depositor)
        controller.create_loan(100_000 * WAD, 90_000 * WAD, 4, sender=borrower)
        assert abs(mp.rate() * (365 * 86400) / WAD - 0.25) < 1e-8
        assert callback.user_collateral(borrower) > 0
        callback.user_checkpoint(borrower, sender=borrower)
        boa.env.time_travel(seconds=3600)
        assert controller.debt(borrower) > 90_000 * WAD
        boa.deal(borrowed, borrower, 100_000 * WAD)
        borrowed.approve(controller, 2**256 - 1, sender=borrower)
        controller.repay(controller.debt(borrower), sender=borrower)
        assert not controller.loan_exists(borrower)
        assert callback.user_collateral(borrower) == 0

        # Interest can make an unchanged collateral position liquidatable.
        maximum = controller.max_borrowable(100_000 * WAD, 4)
        controller.create_loan(100_000 * WAD, maximum, 4, sender=borrower)
        boa.env.time_travel(seconds=365 * 86400)
        assert controller.health(borrower, True) < 0
        boa.deal(borrowed, liquidator, 200_000 * WAD)
        borrowed.approve(controller, 2**256 - 1, sender=liquidator)
        controller.liquidate(borrower, 0, sender=liquidator)
        assert not controller.loan_exists(borrower)
        assert callback.user_collateral(borrower) == 0
        assert collateral.balanceOf(liquidator) > 0
        gauge.withdraw(1000 * WAD, sender=depositor)
        assert gauge.balanceOf(depositor) == 0
        minter = boa.loads_abi(
            '[{"name":"mint","inputs":[{"type":"address"}],"outputs":[],"stateMutability":"nonpayable","type":"function"}]'
        ).at("0xd061D61a4d941c39E5453435B6345Dc261C2fcE0")
        minter.mint(callback.address, sender=borrower)
        minter.mint(gauge.address, sender=depositor)
