import boa
from math import ceil
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant, initialize


class AdiabaticTrader(RuleBasedStateMachine):
    oracle_step = st.floats(min_value=-0.01, max_value=0.01)
    collateral_amount = st.integers(min_value=0, max_value=10**18 * 10**6 // 3000)
    amount_fraction = st.floats(min_value=0, max_value=1.1)
    is_pump = st.booleans()
    n = st.integers(min_value=5, max_value=50)
    t = st.integers(min_value=0, max_value=86400)
    rate = st.integers(min_value=int(1e18 * 0.001 / 365 / 86400), max_value=int(1e18 * 0.2 / 365 / 86400))
    not_enough_allowed = True

    def __init__(self):
        super().__init__()
        self.collateral = self.collateral_token
        self.amm = self.amm
        self.controller = self.controller
        self.borrowed_mul = 10**(18 - self.borrowed_token.decimals())
        self.collateral_mul = 10**(18 - self.collateral_token.decimals())
        with boa.env.prank(self.admin):
            self.monetary_policy.set_rates(int(1e18 * 0.04 / 365 / 86400), int(1e18 * 0.04 / 365 / 86400))
        for user in self.accounts[:2]:
            with boa.env.prank(user):
                self.borrowed_token.approve(self.controller, 2**256 - 1)
                self.collateral_token.approve(self.controller, 2**256 - 1)
                self.borrowed_token.approve(self.amm, 2**256 - 1)
                self.collateral_token.approve(self.amm, 2**256 - 1)

    @initialize(collateral_amount=collateral_amount, n=n)
    def initializer(self, collateral_amount, n):
        # Calculating so that we create it with a nonzero loan
        collateral_amount = int(max(collateral_amount / self.collateral_mul,
                                    n * 10 * ceil(3000 * max(self.borrowed_mul / self.collateral_mul, 1)),
                                    n))
        user = self.accounts[0]
        with boa.env.prank(user):
            boa.deal(collateral, user, collateral_amount)
            loan_amount = self.controller.max_borrowable(collateral_amount, n)
            self.controller.create_loan(collateral_amount, loan_amount, n)
            self.borrowed_token.transfer(self.accounts[1], loan_amount)
            self.loan_amount = loan_amount
            self.collateral_amount = collateral_amount
        self.not_enough = False

    def trade_to_price(self, p):
        user = self.accounts[1]
        with boa.env.prank(user):
            amount, is_pump = self.amm.get_amount_for_price(p)
            if amount > 0:
                if is_pump:
                    if self.not_enough_allowed:
                        if self.borrowed_token.balanceOf(user) < amount:
                            self.not_enough = True
                            return
                    self.amm.exchange(0, 1, amount, 0)
                else:
                    boa.deal(collateral, user, amount)
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
                amount = min(int(self.loan_amount * amount_fraction), self.borrowed_token.balanceOf(user))
                self.amm.exchange(0, 1, amount, 0)
            else:
                amount = int(self.collateral_amount * amount_fraction)
                boa.deal(collateral, user, amount)
                self.amm.exchange(1, 0, amount, 0)

    @rule(t=t)
    def time_travel(self, t):
        boa.env.time_travel(t)

    @rule(min_rate=rate, max_rate=rate)
    def change_rate(self, min_rate, max_rate):
        with boa.env.prank(self.admin):
            self.monetary_policy.set_rates(min(min_rate, max_rate), max(min_rate, max_rate))

    @invariant()
    def health(self):
        if not self.not_enough:
            h = self.controller.health(self.accounts[0])
            assert h > 0


def test_adiabatic_follow(amm, controller, monetary_policy, collateral_token, borrowed_token, price_oracle, accounts, admin):
    AdiabaticTrader.TestCase.settings = settings(max_examples=50, stateful_step_count=50)
    for k, v in locals().items():
        setattr(AdiabaticTrader, k, v)
    run_state_machine_as_test(AdiabaticTrader)
