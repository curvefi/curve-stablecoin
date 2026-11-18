import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    run_state_machine_as_test,
    rule,
    invariant,
)
from random import random
import pytest
from tests.integration.lm_callback.utils import RATE_REDUCTION_TIME, accrue
from tests.utils.constants import MAX_UINT256


class StateMachine(RuleBasedStateMachine):
    user_id = st.integers(min_value=0, max_value=4)
    value = st.integers(min_value=10**16, max_value=10**18 * 10**6 // 3000)
    time = st.integers(min_value=300, max_value=86400 * 90)
    lock_time = st.integers(min_value=86400 * 7, max_value=86400 * 365 * 4)

    def __init__(self):
        super().__init__()
        self.borrowers = [boa.env.generate_address(f"borrower_{i}") for i in range(5)]
        for b in self.borrowers:
            boa.deal(self.collateral_token, b, 1000 * 10**18)
            self.crv.transfer(b, 10**20, sender=self.admin)
            self.collateral_token.approve(self.controller, MAX_UINT256, sender=b)
            self.borrowed_token.approve(self.controller, MAX_UINT256, sender=b)
        self.checkpoint_total_collateral = 0
        # Every borrower is re-checkpointed on every `update_integrals`, so the
        # CRV schedule cache is shared - it mirrors the single cache the callback
        # keeps in `inflation_rate` / `future_epoch_time`
        self.checkpoint_time = boa.env.timestamp
        self.checkpoint_rate = self.crv.rate()
        self.checkpoint_future_epoch = self.crv.start_epoch_time() + RATE_REDUCTION_TIME
        self.integrals = {
            b: {
                "integral": 0,
                "collateral": 0,
            }
            for b in self.borrowers
        }

    def update_integrals(self, user, d_balance=0):
        # Update rewards. Must be called right after every action that checkpoints
        # the callback, otherwise the two CRV schedule caches drift apart
        t1 = boa.env.timestamp
        rate_x_time, self.checkpoint_rate, self.checkpoint_future_epoch = accrue(
            self.crv,
            self.checkpoint_time,
            t1,
            self.checkpoint_rate,
            self.checkpoint_future_epoch,
        )
        for b in self.borrowers:
            integral = self.integrals[b]
            if self.checkpoint_total_collateral > 0:
                integral["integral"] += (
                    rate_x_time
                    * integral["collateral"]
                    // self.checkpoint_total_collateral
                )
            if b == user:
                integral["collateral"] += d_balance
        self.checkpoint_time = t1
        self.checkpoint_total_collateral += d_balance

    @rule(uid=user_id, value=value)
    def deposit(self, uid, value):
        """
        Make a deposit into the `LiquidityGauge` contract.

        Because of the upper bound of `st_value` relative to the initial account
        balances, this rule should never fail.
        """
        user = self.borrowers[uid]
        with boa.env.prank(user):
            balance = self.collateral_token.balanceOf(user)
            value = min(balance, value)

            if value > 0:
                if self.controller.loan_exists(user):
                    self.controller.borrow_more(value, int(value * random() * 2000))
                else:
                    self.controller.create_loan(value, int(value * random() * 2000), 10)
                self.update_integrals(user, value)

                assert self.collateral_token.balanceOf(user) == balance - value
                if (
                    self.integrals[user]["integral"] > 0
                    and self.lm_callback.integrate_fraction(user) > 0
                ):
                    assert self.lm_callback.integrate_fraction(user) == pytest.approx(
                        self.integrals[user]["integral"], rel=1e-13
                    )

    @rule(uid=user_id, value=value)
    def withdraw(self, uid, value):
        """
        Attempt to withdraw from the `LiquidityGauge` contract.
        """
        user = self.borrowers[uid]
        with boa.env.prank(user):
            collateral_in_amm, _, debt, __ = self.controller.user_state(user)
            balance = self.collateral_token.balanceOf(user)
            if collateral_in_amm == 0:
                return

            if value >= collateral_in_amm:
                self.controller.repay(debt)
                remove_amount = collateral_in_amm
            else:
                repay_amount = int(debt * random() * 0.99)
                if repay_amount > 0:
                    self.controller.repay(repay_amount)
                min_collateral_required = self.controller.min_collateral(
                    debt - repay_amount, 10
                )
                remove_amount = min(collateral_in_amm - min_collateral_required, value)
                remove_amount = max(remove_amount, 0)
                if remove_amount > 0:
                    self.controller.remove_collateral(remove_amount)
                elif repay_amount == 0:
                    # Same as in `teardown`: nothing was sent, so the callback
                    # would not have checkpointed while the model does
                    self.lm_callback.user_checkpoint(user)
            self.update_integrals(user, -remove_amount)

            assert self.collateral_token.balanceOf(user) == balance + remove_amount
            if (
                self.integrals[user]["integral"] > 0
                and self.lm_callback.integrate_fraction(user) > 0
            ):
                assert self.lm_callback.integrate_fraction(user) == pytest.approx(
                    self.integrals[user]["integral"], rel=1e-13
                )

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
        user = self.borrowers[uid]
        with boa.env.prank(user):
            self.lm_callback.user_checkpoint(user)
            self.update_integrals(user)
            r1 = self.lm_callback.integrate_fraction(user)
            r2 = self.integrals[user]["integral"]
            assert (r1 > 0) == (r2 > 0)
            if r1 > 0:
                assert r1 == pytest.approx(r2, rel=1e-13)

    @rule(uid=user_id)
    def claim_crv(self, uid):
        """
        Claim user's CRV rewards.
        """
        user = self.borrowers[uid]
        with boa.env.prank(user):
            crv_balance = self.crv.balanceOf(user)
            with boa.env.anchor():
                crv_reward = self.lm_callback.claimable_tokens(user)
            self.minter.mint(self.lm_callback.address)
            assert self.crv.balanceOf(user) - crv_balance == crv_reward
            # Minting checkpoints the callback, so the model has to follow along -
            # otherwise it can miss a CRV epoch the callback has already stepped over
            self.update_integrals(user)

    @invariant()
    def invariant_collateral(self):
        """
        Validate expected balances against actual balances and
        expected total supply against actual total supply.
        """
        for b, integral in self.integrals.items():
            assert self.lm_callback.user_collateral(b) == integral["collateral"]
        assert self.lm_callback.total_collateral() == sum(
            [i["collateral"] for i in self.integrals.values()]
        )

    def teardown(self):
        """
        Final check to ensure that all balances may be withdrawn.
        """
        for b, integral in ((k, v) for k, v in self.integrals.items() if v):
            with boa.env.prank(b):
                initial_collateral = self.collateral_token.balanceOf(b)
                collateral_in_amm = integral["collateral"]
                debt = self.controller.user_state(b)[2]
                if debt > 0:
                    self.controller.repay(debt)
                else:
                    # Nothing is sent, so the callback would not have checkpointed
                    # here while the model does - their cached CRV epochs would
                    # drift apart and the model would keep using the stale rate
                    self.lm_callback.user_checkpoint(b)
                self.update_integrals(b)

                assert not self.controller.loan_exists(b)
                assert (
                    self.collateral_token.balanceOf(b)
                    == initial_collateral + collateral_in_amm
                )

                r1 = self.lm_callback.integrate_fraction(b)
                r2 = integral["integral"]
                assert (r1 > 0) == (r2 > 0)
                if r1 > 0:
                    assert r1 == pytest.approx(r2, rel=1e-13)

                crv_balance = self.crv.balanceOf(b)
                with boa.env.anchor():
                    crv_reward = self.lm_callback.claimable_tokens(b)
                self.minter.mint(self.lm_callback.address)
                assert self.crv.balanceOf(b) - crv_balance == crv_reward


def test_state_machine(
    admin,
    collateral_token,
    borrowed_token,
    crv,
    lm_callback,
    controller,
    minter,
):
    boa.env.time_travel(seconds=7 * 86400)

    StateMachine.TestCase.settings = settings(max_examples=400, stateful_step_count=50)
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    run_state_machine_as_test(StateMachine)
