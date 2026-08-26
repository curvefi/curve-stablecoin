import boa
from hypothesis import assume, event, note
from hypothesis.stateful import rule
from hypothesis.strategies import data, integers

from tests.fuzz.stateful.test_targeted_stateful import TargetedMetricsMixin
from tests.fuzz.stateful.stateful_base import LlamalendStatefulBase
from tests.utils.constants import MAX_UINT256, WAD
from tests.utils.deployers import FAKE_LEVERAGE_DEPLOYER


class LiquidationModesStateful(TargetedMetricsMixin, LlamalendStatefulBase):
    """
    Targeted liquidation suite for paths that the base hard-liquidation rule does
    not isolate: partial liquidation, self-liquidation, and callback liquidation.
    """

    price_multiplier_bps = integers(min_value=1_000, max_value=8_500)
    partial_frac = integers(min_value=1, max_value=WAD - 1)

    def initialize_market(self, market):
        super().initialize_market(market)
        self.fake_leverage = FAKE_LEVERAGE_DEPLOYER.deploy(
            self.borrowed_token.address,
            self.collateral_token.address,
            self.controller.address,
            self.price_oracle.price(),
        )

    def make_liquidatable_user(self, data, multiplier_bps: int):
        self.ensure_loan_near_active_band(data, "liquidation")

        price_before = int(self.price_oracle.price())
        price_after = max(price_before * multiplier_bps // 10_000, 1)
        with boa.env.prank(self.admin):
            self.price_oracle.set_price(price_after)
        self.record_oracle_jump(price_before, price_after)

        positions = self.controller.users_to_liquidate(0, len(self.users))
        assume(len(positions) > 0)
        user = positions[0].user
        assume(self.controller.loan_exists(user))
        event("stateful:liquidation:made_liquidatable")
        return user

    def fund_liquidation(self, holder: str, user: str, frac: int):
        required = int(self.controller.tokens_to_liquidate(user, frac))
        assume(required > 0)
        boa.deal(self.borrowed_token, holder, required + 1)
        with boa.env.prank(holder):
            self.borrowed_token.approve(self.controller.address, MAX_UINT256)
        return required

    @rule(data=data(), multiplier_bps=price_multiplier_bps, frac=partial_frac)
    def partial_liquidation(self, data, multiplier_bps, frac):
        note("[PARTIAL LIQUIDATION]")
        user = self.make_liquidatable_user(data, multiplier_bps)
        liquidator = boa.env.generate_address("partial_liquidator")
        debt_before = int(self.controller.debt(user))
        self.fund_liquidation(liquidator, user, frac)

        with boa.env.prank(liquidator):
            self.controller.liquidate(user, 0, frac)

        assert self.controller.debt(user) < debt_before
        self.sync_users()
        event("stateful:liquidate:partial")

    @rule(data=data(), multiplier_bps=price_multiplier_bps)
    def self_liquidation(self, data, multiplier_bps):
        note("[SELF LIQUIDATION]")
        user = self.make_liquidatable_user(data, multiplier_bps)
        self.fund_liquidation(user, user, WAD)

        with boa.env.prank(user):
            self.controller.liquidate(user, 0)

        assert not self.controller.loan_exists(user)
        self.sync_users()
        event("stateful:liquidate:self")

    @rule(data=data(), multiplier_bps=price_multiplier_bps, frac=partial_frac)
    def callback_liquidation(self, data, multiplier_bps, frac):
        note("[CALLBACK LIQUIDATION]")
        user = self.make_liquidatable_user(data, multiplier_bps)
        liquidator = boa.env.generate_address("callback_liquidator")
        debt_before = int(self.controller.debt(user))
        self.fund_liquidation(self.fake_leverage.address, user, frac)

        with boa.env.prank(liquidator):
            self.fake_leverage.approve_all()
            self.controller.liquidate(user, 0, frac, self.fake_leverage.address, b"")

        assert self.controller.debt(user) < debt_before
        self.sync_users()
        event("stateful:liquidate:callback")


TestLiquidationModes = LiquidationModesStateful.TestCase
