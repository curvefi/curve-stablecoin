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
    ratio = st.floats(min_value=0, max_value=2)
    time_shift = st.integers(min_value=1, max_value=30 * 86400)

    def __init__(self):
        super().__init__()
        self.anchor = boa.env.anchor()
        self.anchor.__enter__()
        self.A = self.market_amm.A()
        # Check debt ceiling?

    # Auxiliary methods #
    def get_stablecoins(self, user):
        with boa.env.prank(self.accounts[0]):
            self.market_controller.collect_fees()
            if user != self.accounts[0]:
                amount = self.stablecoin.balanceOf(self.accounts[0])
                if amount > 0:
                    self.stablecoin.transfer(user, amount)

    def remove_stablecoins(self, user):
        if user != self.accounts[0]:
            with boa.env.prank(user):
                amount = self.stablecoin.balanceOf(user)
                if amount > 0:
                    self.stablecoin.transfer(self.accounts[0], amount)

    # Borrowing and returning #
    @rule(y=collateral_amount, n=n, uid=user_id, ratio=ratio)
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

    @rule(ratio=ratio, uid=user_id)
    def repay(self, ratio, uid):
        user = self.accounts[uid]
        debt = self.market_controller.debt(user)
        amount = int(ratio * debt)
        self.get_stablecoins(user)
        with boa.env.prank(user):
            if debt == 0:
                with pytest.raises(BoaError):
                    self.market_controller.repay(amount, user)
            else:
                self.market_controller.repay(amount, user)
        self.remove_stablecoins(user)

    @rule(y=collateral_amount, uid=user_id)
    def add_collateral(self, y, uid):
        user = self.accounts[uid]
        self.collateral_token._mint_for_testing(user, y)

        with boa.env.prank(user):
            if self.market_controller.loan_exists(user):
                self.market_controller.add_collateral(y, user)
            else:
                with pytest.raises(BoaError):
                    self.market_controller.add_collateral(y, user)

    @rule(dt=time_shift)
    def time_travel(self, dt):
        boa.env.vm.patch.timestamp += dt
        boa.env.vm.patch.block_number += dt // 13 + 1

    def teardown(self):
        self.anchor.__exit__(None, None, None)


def test_big_fuzz(
        market_amm, market_controller, monetary_policy, collateral_token, stablecoin, price_oracle, accounts, admin):
    BigFuzz.TestCase.settings = settings(max_examples=500, stateful_step_count=10, deadline=timedelta(seconds=1000))
    for k, v in locals().items():
        setattr(BigFuzz, k, v)
    run_state_machine_as_test(BigFuzz)
