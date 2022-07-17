import pytest
import boa
from boa.contract import BoaError
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule
from datetime import timedelta


class BigFuzz(RuleBasedStateMachine):
    collateral_amount = st.integers(min_value=0, max_value=10**18 * 10**6 // 3000)
    loan_amount = st.integers(min_value=0, max_value=10**18 * 10**6 // 3000)
    n = st.integers(min_value=5, max_value=50)
    user_id = st.integers(min_value=0, max_value=9)
    loan_frac = st.floats(min_value=0, max_value=2)

    def __init__(self):
        super().__init__()
        self.anchor = boa.env.anchor()
        self.anchor.__enter__()
        self.A = self.market_amm.A()

    @rule(y=collateral_amount, n=n, uid=user_id, ratio=loan_frac)
    def deposit(self, y, n, ratio, uid):
        user = self.accounts[uid]
        debt = int(ratio * 3000 * y)
        with boa.env.prank(user):
            self.collateral_token._mint_for_testing(user, y)
            if (self.market_controller.max_borrowable(y, n) < debt or y // n <= 100
                    or debt == 0 or self.market_controller.loan_exists(user)):
                with pytest.raises(BoaError):
                    self.market_controller.create_loan(y, debt, n)
                return
            else:
                self.market_controller.create_loan(y, debt, n)
            self.stablecoin.transfer(self.accounts[0], debt)

    def teardown(self):
        self.anchor.__exit__(None, None, None)


def test_big_fuzz(
        market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    BigFuzz.TestCase.settings = settings(max_examples=10, stateful_step_count=10, deadline=timedelta(seconds=1000))
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    run_state_machine_as_test(BigFuzz)
