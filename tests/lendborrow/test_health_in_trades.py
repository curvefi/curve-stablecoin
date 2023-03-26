import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant, initialize


class AdiabaticTrader(RuleBasedStateMachine):
    oracle_step = st.floats(min_value=-0.01, max_value=0.01)
    collateral_amount = st.integers(min_value=10**10, max_value=10**18 * 10**6 // 3000)
    amount_fraction = st.floats(min_value=0, max_value=1.1)
    is_pump = st.booleans()
    n = st.integers(min_value=5, max_value=50)
    t = st.integers(min_value=0, max_value=86400)
    rate = st.integers(min_value=0, max_value=int(1e18 * 0.2 / 365 / 86400))

    def __init__(self):
        super().__init__()
        self.collateral = self.collateral_token
        self.amm = self.market_amm
        self.controller = self.market_controller
        with boa.env.prank(self.admin):
            self.monetary_policy.set_rate(int(1e18 * 0.04 / 365 / 86400))

    @initialize(collateral_amount=collateral_amount, n=n)
    def initializer(self, collateral_amount, n):
        user = self.accounts[0]
        with boa.env.prank(user):
            self.collateral._mint_for_testing(user, collateral_amount)
            loan_amount = self.controller.max_borrowable(collateral_amount, n)
            self.controller.create_loan(collateral_amount, loan_amount, n)
            self.stablecoin.transfer(self.accounts[1], loan_amount)
            self.loan_amount = loan_amount
            self.collateral_amount = collateral_amount

    def trade_to_price(self, p):
        user = self.accounts[1]
        with boa.env.prank(user):
            self.controller.collect_fees()
            amount, is_pump = self.amm.get_amount_for_price(p)
            if amount > 0:
                if is_pump:
                    self.amm.exchange(0, 1, amount, 0)
                else:
                    self.collateral._mint_for_testing(user, amount)
                    self.amm.exchange(1, 0, amount, 0)

    @rule(oracle_step=oracle_step)
    def shift_oracle(self, oracle_step):
        self.trade_to_price(self.price_oracle.price())
        p = int(self.price_oracle.price() * (1 + oracle_step))
        with boa.env.prank(self.admin):
            self.price_oracle.set_price(p)
        self.trade_to_price(p)

    @rule(amount_fraction=amount_fraction, is_pump=is_pump)
    def random_trade(self, amount_fraction, is_pump):
        user = self.accounts[0]
        with boa.env.prank(user):
            if is_pump:
                amount = min(int(self.loan_amount * amount_fraction), self.stablecoin.balanceOf(user))
                self.amm.exchange(0, 1, amount, 0)
            else:
                amount = int(self.collateral_amount * amount_fraction)
                self.collateral._mint_for_testing(user, amount)
                self.amm.exchange(1, 0, amount, 0)

    @rule(t=t)
    def time_travel(self, t):
        boa.env.time_travel(t)

    @rule(rate=rate)
    def change_rate(self, rate):
        with boa.env.prank(self.admin):
            self.monetary_policy.set_rate(rate)

    @invariant()
    def health(self):
        assert self.controller.health(self.accounts[0]) > 0


def test_adiabatic_follow(market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    AdiabaticTrader.TestCase.settings = settings(max_examples=50, stateful_step_count=50)
    for k, v in locals().items():
        setattr(AdiabaticTrader, k, v)
    run_state_machine_as_test(AdiabaticTrader)


def test_approval_worked(market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(AdiabaticTrader, k, v)
    with boa.env.anchor():
        state = AdiabaticTrader()
        state.initializer(collateral_amount=10000000000, n=7)
        state.shift_oracle(oracle_step=-5581384867293334/1e18)
        state.shift_oracle(oracle_step=-6965451302984162/1e18)


def test_shift_oracle_fail(market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    for k, v in locals().items():
        setattr(AdiabaticTrader, k, v)
    # Fail which was due to rounding eror in get_amount_for_price
    with boa.env.anchor():
        state = AdiabaticTrader()
        state.initializer(collateral_amount=10000000257, n=5)
        state.change_rate(rate=1)
        state.change_rate(rate=0)
        state.change_rate(rate=0)
        state.shift_oracle(oracle_step=-7545700784685381/1e18)
        state.shift_oracle(oracle_step=-9113745346295811/1e18)
        state.shift_oracle(oracle_step=0)
