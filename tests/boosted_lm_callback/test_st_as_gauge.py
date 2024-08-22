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
        self.checkpoint_supply = 0
        self.checkpoint_working_supply = 0
        self.checkpoint_rate = self.crv.rate()
        self.integrals = {addr: {
            "checkpoint": boa.env.vm.patch.timestamp,
            "integral": 0,
            "balance": 0,
            "working_balance": 0
        } for addr in self.accounts[:5]}

    def update_integrals(self, user, d_balance=0):
        # Update rewards
        t1 = boa.env.vm.patch.timestamp
        t_epoch = self.crv.start_epoch_time_write(sender=self.admin)
        rate1 = self.crv.rate()
        for acct in self.accounts[:5]:
            integral = self.integrals[acct]
            if integral["checkpoint"] >= t_epoch:
                rate_x_time = (t1 - integral["checkpoint"]) * rate1
            else:
                rate_x_time = (t_epoch - integral["checkpoint"]) * self.checkpoint_rate + (t1 - t_epoch) * rate1
            if self.checkpoint_working_supply > 0:
                integral["integral"] += rate_x_time * integral["working_balance"] // self.checkpoint_working_supply
            integral["checkpoint"] = t1
            if acct == user:
                integral["balance"] += d_balance
        self.checkpoint_supply += d_balance
        self.checkpoint_rate = rate1

        # Update working balance and supply
        voting_balance = self.voting_escrow_delegation_mock.adjusted_balance_of(user)
        voting_total = self.voting_escrow.totalSupply()
        integral = self.integrals[user]

        lim = integral["balance"] * 40 // 100
        if voting_total > 0:
            lim += self.checkpoint_supply * voting_balance // voting_total * 60 // 100
        lim = min(integral["balance"], lim)

        old_bal = integral["working_balance"]
        integral["working_balance"] = lim
        self.checkpoint_working_supply += lim - old_bal

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
                if self.integrals[user]["integral"] > 0 and self.boosted_lm_callback.integrate_fraction(user) > 0:
                    assert approx(self.boosted_lm_callback.integrate_fraction(user), self.integrals[user]["integral"], 1e-13)

    @rule(uid=user_id, value=value)
    def withdraw(self, uid, value):
        """
        Attempt to withdraw from the `LiquidityGauge` contract.
        """
        user = self.accounts[uid]
        with boa.env.prank(user):
            _value = min(value, self.integrals[user]["balance"])

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
            if self.integrals[user]["integral"] > 0 and self.boosted_lm_callback.integrate_fraction(user) > 0:
                assert approx(self.boosted_lm_callback.integrate_fraction(user), self.integrals[user]["integral"], 1e-13)

    @rule(dt=time)
    def advance_time(self, dt):
        """
        Advance the clock.
        """
        boa.env.time_travel(seconds=dt)

    @rule(uid=user_id, dt=lock_time)
    def create_lock(self, uid, dt):
        """
        Create lock in voting escrow to get boosted.
        """
        user = self.accounts[uid]
        if self.voting_escrow.locked(user)[0] == 0:
            self.voting_escrow.create_lock(10 ** 20, boa.env.vm.patch.timestamp + dt, sender=user)

    @rule(uid=user_id)
    def withdraw_from_ve(self, uid):
        """
        Withdraw expired lock from voting escrow.
        """
        user = self.accounts[uid]
        if 0 < self.voting_escrow.locked__end(user) < boa.env.vm.patch.timestamp:
            self.voting_escrow.withdraw(sender=user)

    @rule(uid=user_id)
    def checkpoint(self, uid):
        """
        Create a new user checkpoint.
        """
        user = self.accounts[uid]
        with boa.env.prank(user):
            self.boosted_lm_callback.user_checkpoint(user)
            self.update_integrals(user)
            if self.integrals[user]["integral"] > 0 and self.boosted_lm_callback.integrate_fraction(user) > 0:
                assert approx(self.boosted_lm_callback.integrate_fraction(user), self.integrals[user]["integral"], 1e-13)

    @invariant()
    def invariant_collateral(self):
        """
        Validate expected balances against actual balances and
        expected total supply against actual total supply.
        """
        for account, integral in self.integrals.items():
            assert self.boosted_lm_callback.user_collateral(account) == integral["balance"]
        assert self.boosted_lm_callback.total_collateral() == sum([i["balance"] for i in self.integrals.values()])

    @invariant()
    def invariant_working_collateral(self):
        """
        Validate expected working balances against actual working balances and
        expected working supply against actual working supply.
        """
        for account, integral in self.integrals.items():
            y1 = self.boosted_lm_callback.working_collateral(account)
            y2 = integral["working_balance"]
            assert approx(y1, y2, 1e-17) or abs(y1 - y2) < 100

        Y1 = self.boosted_lm_callback.working_supply()
        Y2 = sum([i["working_balance"] for i in self.integrals.values()])
        assert approx(Y1, Y2, 1e-17) or abs(Y1 - Y2) < 10000

    def teardown(self):
        """
        Final check to ensure that all balances may be withdrawn.
        """
        for account, integral in ((k, v) for k, v in self.integrals.items() if v):
            initial = self.collateral_token.balanceOf(account)
            debt = self.market_controller.user_state(account)[2]
            self.market_controller.repay(debt, sender=account)
            self.update_integrals(account)

            assert not self.market_controller.loan_exists(account)
            assert self.collateral_token.balanceOf(account) == initial + integral["balance"]
            assert (self.integrals[account]["integral"] > 0) == (self.boosted_lm_callback.integrate_fraction(account) > 0)
            if self.integrals[account]["integral"] > 0:
                assert approx(self.boosted_lm_callback.integrate_fraction(account), self.integrals[account]["integral"], 1e-13)


def test_state_machine(
        accounts,
        admin,
        collateral_token,
        crv,
        boosted_lm_callback,
        gauge_controller,
        market_controller,
        voting_escrow,
        voting_escrow_delegation_mock,
):
    for acct in accounts[:5]:
        with boa.env.prank(admin):
            collateral_token._mint_for_testing(acct, 1000 * 10**18)
            crv.transfer(acct, 10 ** 20)

        with boa.env.prank(acct):
            collateral_token.approve(market_controller, 2 ** 256 - 1)
            crv.approve(voting_escrow, 2 ** 256 - 1)

    # Wire up Gauge to the controller to have proper rates and stuff
    with boa.env.prank(admin):
        gauge_controller.add_type("crvUSD Market")
        gauge_controller.change_type_weight(0, 10 ** 18)
        gauge_controller.add_gauge(boosted_lm_callback.address, 0, 10 ** 18)

    boa.env.time_travel(seconds=7 * 86400)

    StateMachine.TestCase.settings = settings(max_examples=400, stateful_step_count=50)
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    run_state_machine_as_test(StateMachine)
