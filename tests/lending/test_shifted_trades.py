from .test_health_in_trades import AdiabaticTrader
from hypothesis import strategies as st
from hypothesis.stateful import initialize, run_state_machine_as_test
from hypothesis import settings


class ShiftedTrader(AdiabaticTrader):
    oracle_shift = st.floats(min_value=-0.05, max_value=0.05)
    collateral_amount = st.integers(min_value=10**10, max_value=10**18 * 10**6 // 3000)
    n = st.integers(min_value=5, max_value=50)
    not_enough_allowed = True

    @initialize(collateral_amount=collateral_amount, n=n, oracle_shift=oracle_shift)
    def initializer(self, collateral_amount, n, oracle_shift):
        super().initializer(collateral_amount, n)
        self.price_shift = oracle_shift
        self.shift_oracle(0)
        self.not_enough = False

    def trade_to_price(self, p):
        super().trade_to_price(int(p * (1 + self.price_shift)))


def test_adiabatic_shifted(market_amm, filled_controller, market_mpolicy, collateral_token, borrowed_token, price_oracle, accounts, admin):
    ShiftedTrader.TestCase.settings = settings(max_examples=50, stateful_step_count=50)
    for k, v in locals().items():
        setattr(ShiftedTrader, k, v)
    run_state_machine_as_test(ShiftedTrader)
