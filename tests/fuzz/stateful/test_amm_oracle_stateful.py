import boa
from hypothesis import assume, event, note
from hypothesis.stateful import invariant, rule
from hypothesis.strategies import data, integers

from tests.fuzz.stateful.test_targeted_stateful import (
    AmmVolumeTargetStateful,
    TargetedMetricsMixin,
)
from tests.fuzz.stateful.stateful_base import LlamalendStatefulBase
from tests.fuzz.strategies import token_amounts
from tests.utils import max_approve


class AmmAccountingStateful(AmmVolumeTargetStateful):
    """
    AMM exchange target with solvency/accounting invariants from the old AMM
    stateful suites.
    """

    def observed_bands(self):
        active = int(self.amm.active_band())
        bands = set(range(active - 16, active + 96))
        for user in self.users:
            n1, n2 = self.amm.read_user_tick_numbers(user)
            bands.update(range(int(n1), int(n2) + 1))
        return bands

    @invariant()
    def amm_token_balances_cover_observed_bands(self):
        borrowed_mul = 10 ** (18 - int(self.borrowed_token.decimals()))
        collateral_mul = 10 ** (18 - int(self.collateral_token.decimals()))

        x_sum = 0
        y_sum = 0
        for band in self.observed_bands():
            x_sum += int(self.amm.bands_x(band))
            y_sum += int(self.amm.bands_y(band))

        assert self.borrowed_token.balanceOf(self.amm) * borrowed_mul >= x_sum
        assert self.collateral_token.balanceOf(self.amm) * collateral_mul >= y_sum


class AdiabaticOracleStateful(TargetedMetricsMixin, LlamalendStatefulBase):
    """
    Move market price toward the oracle before and after oracle shifts, then
    check borrower health. This steals the old adiabatic/shifted-trade idea
    without adding it to the baseline state machine.
    """

    oracle_step_bps = integers(min_value=-100, max_value=100)

    def ensure_loan(self, data):
        if self.users:
            return self.users[0]

        N = data.draw(integers(min_value=5, max_value=20), label="adiabatic_N")
        user = boa.env.generate_address("adiabatic_user")
        collateral = data.draw(
            token_amounts(
                int(self.collateral_token.decimals()),
                min_value=1_000,
                max_value=1_000_000,
            ),
            label="adiabatic_collateral",
        )
        max_debt = min(
            int(self.controller.max_borrowable(collateral, N)),
            int(self.controller.available_balance()),
        )
        borrowed_unit = 10 ** int(self.borrowed_token.decimals())
        assume(max_debt >= borrowed_unit)

        debt_bps = data.draw(
            integers(min_value=1_000, max_value=5_000),
            label="adiabatic_debt_bps",
        )
        debt = max(max_debt * debt_bps // 10_000, borrowed_unit)
        assume(debt <= max_debt)

        self.create_loan(user, collateral, debt, N)
        assume(self.controller.health(user) > 0)
        event("stateful:create_loan")
        event("stateful:adiabatic:seeded_loan")
        return user

    def trade_to_price(self, price: int):
        amount, is_pump = self.amm.get_amount_for_price(price)
        if amount <= 0:
            return

        trader = boa.env.generate_address("adiabatic_trader")
        i = 0 if is_pump else 1
        j = 1 - i
        token = self.borrowed_token if i == 0 else self.collateral_token
        boa.deal(token, trader, token.balanceOf(trader) + amount)

        band_before = int(self.amm.active_band())
        with boa.env.prank(trader):
            max_approve(token, self.amm.address)
            spent, _ = self.amm.exchange(i, j, amount, 0)
        band_after = int(self.amm.active_band())

        self.record_amm_volume(i, int(spent))
        self.record_active_band_move(band_before, band_after)
        event("stateful:adiabatic:trade_to_price")

    @rule(step_bps=oracle_step_bps, data=data())
    def adiabatic_oracle_shift(self, step_bps, data):
        note("[ADIABATIC ORACLE SHIFT]")
        user = self.ensure_loan(data)

        old_price = int(self.price_oracle.price())
        self.trade_to_price(old_price)

        new_price = max(old_price * (10_000 + step_bps) // 10_000, 1)
        band_before = int(self.amm.active_band())
        with boa.env.prank(self.admin):
            self.price_oracle.set_price(new_price)
        band_after = int(self.amm.active_band())

        self.record_oracle_jump(old_price, new_price)
        self.record_active_band_move(band_before, band_after)
        self.trade_to_price(new_price)

        assume(self.controller.loan_exists(user))
        assert self.controller.health(user) > 0
        event("stateful:adiabatic_oracle_shift")
        if step_bps > 0:
            event("stateful:adiabatic_oracle_shift:up")
        elif step_bps < 0:
            event("stateful:adiabatic_oracle_shift:down")
        else:
            event("stateful:adiabatic_oracle_shift:flat")


TestAmmAccounting = AmmAccountingStateful.TestCase
TestAdiabaticOracle = AdiabaticOracleStateful.TestCase
