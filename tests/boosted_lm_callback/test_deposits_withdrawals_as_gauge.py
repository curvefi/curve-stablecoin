from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant
from random import random
import boa


class StateMachine(RuleBasedStateMachine):
    user_id = st.integers(min_value=0, max_value=4)
    value = st.integers(min_value=10**16, max_value=10 ** 18 * 10 ** 6 // 3000)
    time = st.integers(min_value=0, max_value=86400 * 365)

    def __init__(self):
        super().__init__()
        self.balances = {i: 0 for i in self.accounts[:5]}

    @rule(uid=user_id, value=value)
    def deposit(self, uid, value):
        """
        Make a deposit into the `LiquidityGauge` contract.

        Because of the upper bound of `st_value` relative to the initial account
        balances, this rule should never fail.
        """
        user = self.accounts[uid]
        with boa.env.prank(user):
            balance = self.collateral_token.balanceOf(user)

            if self.market_controller.loan_exists(user):
                self.market_controller.borrow_more(value, int(value * random() * 2000))
            else:
                self.market_controller.create_loan(value, int(value * random() * 2000), 10)
            self.balances[user] += value

            assert self.collateral_token.balanceOf(user) == balance - value

    @rule(uid=user_id, value=value)
    def withdraw(self, uid, value):
        """
        Attempt to withdraw from the `LiquidityGauge` contract.
        """
        user = self.accounts[uid]
        with boa.env.prank(user):
            _value = min(value, self.balances[user])

            collateral_in_amm, _, debt, __ = self.market_controller.user_state(user)
            balance = self.collateral_token.balanceOf(user)
            if collateral_in_amm == 0:
                return

            if value >= collateral_in_amm:
                self.market_controller.repay(debt)
                remove_amount = collateral_in_amm
            else:
                repay_amount = int(debt * random() * 0.99)
                self.market_controller.repay(repay_amount)
                remove_amount = min(int(self.market_controller.min_collateral(debt - repay_amount, 10) * 0.99), value)
                self.market_controller.remove_collateral(remove_amount)
            self.balances[user] -= remove_amount

            assert self.collateral_token.balanceOf(user) == balance + remove_amount

    @rule(dt=time)
    def advance_time(self, dt):
        """
        Advance the clock.
        """
        boa.env.time_travel(seconds=dt)

    @rule(uid=user_id)
    def checkpoint(self, uid):
        """
        Create a new user checkpoint.
        """
        user = self.accounts[uid]
        with boa.env.prank(user):
            self.boosted_lm_callback.user_checkpoint(user)

    @invariant()
    def balances(self):
        """
        Validate expected balances against actual balances.
        """
        for account, balance in self.balances.items():
            assert self.boosted_lm_callback.user_collateral(account) == balance

    @invariant()
    def total_supply(self):
        """
        Validate expected total supply against actual total supply.
        """
        assert self.boosted_lm_callback.total_collateral() == sum(self.balances.values())

    def teardown(self):
        """
        Final check to ensure that all balances may be withdrawn.
        """
        for account, balance in ((k, v) for k, v in self.balances.items() if v):
            initial = self.collateral_token.balanceOf(account)
            debt = self.market_controller.user_state(account)[2]
            self.market_controller.repay(debt, sender=account)

            assert not self.market_controller.loan_exists(account)
            assert self.collateral_token.balanceOf(account) == initial + balance


def test_state_machine(accounts, admin, collateral_token, crv, boosted_lm_callback, gauge_controller, market_controller):
    # fund accounts to be used in the test
    for acct in accounts[:5]:
        collateral_token._mint_for_testing(acct, 1000 * 10**18, sender=admin)

    # approve gauge_v3 from the funded accounts
    for acct in accounts[:5]:
        collateral_token.approve(market_controller, 2 ** 256 - 1, sender=acct)

    StateMachine.TestCase.settings = settings(max_examples=30, stateful_step_count=25)
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    run_state_machine_as_test(StateMachine)
