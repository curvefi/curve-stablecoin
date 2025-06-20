import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant
from random import random
from ..conftest import approx


class StateMachine(RuleBasedStateMachine):
    user_id = st.integers(min_value=0, max_value=4)
    value = st.integers(min_value=10**16, max_value=10 ** 18 * 10 ** 6 // 3000)
    time = st.integers(min_value=300, max_value=86400 * 90)
    lock_time = st.integers(min_value=86400 * 7, max_value=86400 * 365 * 4)

    def __init__(self):
        super().__init__()
        self.checkpoint_total_collateral = 0
        self.checkpoint_rate = self.crv.rate()
        self.integrals = {addr: {
            "checkpoint": boa.env.evm.patch.timestamp,
            "integral": 0,
            "collateral": 0,
        } for addr in self.accounts[:5]}

    def update_integrals(self, user, d_balance=0):
        # Update rewards
        t1 = boa.env.evm.patch.timestamp
        t_epoch = self.crv.start_epoch_time_write(sender=self.admin)
        rate1 = self.crv.rate()
        for acct in self.accounts[:5]:
            integral = self.integrals[acct]
            if integral["checkpoint"] >= t_epoch:
                rate_x_time = (t1 - integral["checkpoint"]) * rate1
            else:
                rate_x_time = (t_epoch - integral["checkpoint"]) * self.checkpoint_rate + (t1 - t_epoch) * rate1
            if self.checkpoint_total_collateral > 0:
                integral["integral"] += rate_x_time * integral["collateral"] // self.checkpoint_total_collateral
            integral["checkpoint"] = t1
            if acct == user:
                integral["collateral"] += d_balance
        self.checkpoint_total_collateral += d_balance
        self.checkpoint_rate = rate1

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
            value = min(balance, value)

            if value > 0:
                if self.market_controller.loan_exists(user):
                    self.market_controller.borrow_more(value, int(value * random() * 2000))
                else:
                    self.market_controller.create_loan(value, int(value * random() * 2000), 10)
                self.update_integrals(user, value)

                assert self.collateral_token.balanceOf(user) == balance - value
                if self.integrals[user]["integral"] > 0 and self.lm_callback.integrate_fraction(user) > 0:
                    assert approx(self.lm_callback.integrate_fraction(user), self.integrals[user]["integral"], 1e-13)

    @rule(uid=user_id, value=value)
    def withdraw(self, uid, value):
        """
        Attempt to withdraw from the `LiquidityGauge` contract.
        """
        user = self.accounts[uid]
        with boa.env.prank(user):
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
                min_collateral_required = self.market_controller.min_collateral(debt - repay_amount, 10)
                remove_amount = min(collateral_in_amm - min_collateral_required, value)
                remove_amount = max(remove_amount, 0)
                if remove_amount > 0:
                    self.market_controller.remove_collateral(remove_amount)
            self.update_integrals(user, -remove_amount)

            assert self.collateral_token.balanceOf(user) == balance + remove_amount
            if self.integrals[user]["integral"] > 0 and self.lm_callback.integrate_fraction(user) > 0:
                assert approx(self.lm_callback.integrate_fraction(user), self.integrals[user]["integral"], 1e-13)

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
            self.lm_callback.user_checkpoint(user)
            self.update_integrals(user)
            r1 = self.lm_callback.integrate_fraction(user)
            r2 = self.integrals[user]["integral"]
            assert (r1 > 0) == (r2 > 0)
            if r1 > 0:
                assert approx(r1, r2, 1e-13)

    @rule(uid=user_id)
    def claim_crv(self, uid):
        """
        Claim user's CRV rewards.
        """
        user = self.accounts[uid]
        with boa.env.prank(user):
            crv_balance = self.crv.balanceOf(user)
            with boa.env.anchor():
                crv_reward = self.lm_callback.claimable_tokens(user)
            self.minter.mint(self.lm_callback.address)
            assert self.crv.balanceOf(user) - crv_balance == crv_reward

    @invariant()
    def invariant_collateral(self):
        """
        Validate expected balances against actual balances and
        expected total supply against actual total supply.
        """
        for account, integral in self.integrals.items():
            assert self.lm_callback.user_collateral(account) == integral["collateral"]
        assert self.lm_callback.total_collateral() == sum([i["collateral"] for i in self.integrals.values()])

    def teardown(self):
        """
        Final check to ensure that all balances may be withdrawn.
        """
        for account, integral in ((k, v) for k, v in self.integrals.items() if v):
            with boa.env.prank(account):
                initial_collateral = self.collateral_token.balanceOf(account)
                collateral_in_amm = integral["collateral"]
                debt = self.market_controller.user_state(account)[2]
                self.market_controller.repay(debt)
                self.update_integrals(account)

                assert not self.market_controller.loan_exists(account)
                assert self.collateral_token.balanceOf(account) == initial_collateral + collateral_in_amm

                r1 = self.lm_callback.integrate_fraction(account)
                r2 = integral["integral"]
                assert (r1 > 0) == (r2 > 0)
                if r1 > 0:
                    assert approx(r1, r2, 1e-13)

                crv_balance = self.crv.balanceOf(account)
                with boa.env.anchor():
                    crv_reward = self.lm_callback.claimable_tokens(account)
                self.minter.mint(self.lm_callback.address)
                assert self.crv.balanceOf(account) - crv_balance == crv_reward


def test_state_machine(
        accounts,
        admin,
        collateral_token,
        crv,
        lm_callback,
        market_controller,
        minter,
):
    for acct in accounts[:5]:
        with boa.env.prank(admin):
            collateral_token._mint_for_testing(acct, 1000 * 10**18)
            crv.transfer(acct, 10 ** 20)

        with boa.env.prank(acct):
            collateral_token.approve(market_controller, 2 ** 256 - 1)

    boa.env.time_travel(seconds=7 * 86400)

    StateMachine.TestCase.settings = settings(max_examples=400, stateful_step_count=50)
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    run_state_machine_as_test(StateMachine)
