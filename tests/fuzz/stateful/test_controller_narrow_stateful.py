import boa
import pytest
from hypothesis import assume, event, note
from hypothesis.stateful import invariant, precondition, rule
from hypothesis.strategies import data, integers, sampled_from

from tests.fuzz.stateful.test_controller_stateful import ControllerStateful
from tests.fuzz.strategies import (
    loan_amounts_for_create,
    loan_increments_for_borrow_more,
    ticks,
    token_amounts,
)


class HealthPreviewStateful(ControllerStateful):
    """
    Focused controller suite that treats public health preview methods as oracles.
    """

    def assert_health_matches_preview(self, user: str, preview: int, full: bool):
        debt = self.controller.debt(user)
        if debt == 0:
            return

        actual = self.controller.health(user, full)
        assert actual == pytest.approx(preview, rel=1e-4, abs=max(1, 10**18 // debt))

    @rule(N=ticks, data=data())
    def create_loan_with_health_preview(self, N, data):
        note("[CREATE LOAN HEALTH PREVIEW]")
        user_label = f"health_preview_user_{len(self.users)}"
        user = boa.env.generate_address(user_label)
        collateral, debt = data.draw(
            loan_amounts_for_create(self.controller, N),
            label=f"health_preview_loan_amounts({user_label})",
        )

        preview = self.controller.create_loan_health_preview(
            collateral, debt, N, user, False
        )
        preview_full = self.controller.create_loan_health_preview(
            collateral, debt, N, user, True
        )
        self.create_loan(user, collateral, debt, N)

        self.assert_health_matches_preview(user, preview, False)
        self.assert_health_matches_preview(user, preview_full, True)
        event("stateful:health_preview:create_loan")

    @precondition(lambda self: len(self.users) > 0)
    @rule(data=data())
    def repay_with_health_preview(self, data):
        note("[REPAY HEALTH PREVIEW]")
        user = data.draw(sampled_from(self.users), label="health_preview_repay_user")
        debt = int(self.controller.debt(user))
        assume(debt > 1)

        repay_amount = data.draw(
            integers(min_value=1, max_value=debt - 1),
            label="health_preview_repay_amount",
        )
        preview = self.controller.repay_health_preview(
            0, repay_amount, user, False, False
        )
        preview_full = self.controller.repay_health_preview(
            0, repay_amount, user, False, True
        )

        self.repay(user, repay_amount)
        self.assert_health_matches_preview(user, preview, False)
        self.assert_health_matches_preview(user, preview_full, True)
        event("stateful:health_preview:repay")

    @precondition(lambda self: len(self.users) > 0)
    @rule(data=data())
    def add_collateral_with_health_preview(self, data):
        note("[ADD COLLATERAL HEALTH PREVIEW]")
        user = data.draw(sampled_from(self.users), label="health_preview_add_user")
        decimals = int(self.collateral_token.decimals())
        collateral = data.draw(
            token_amounts(decimals, min_value=1, max_value=1_000_000),
            label="health_preview_add_collateral",
        )

        preview = self.controller.add_collateral_health_preview(
            collateral, user, False
        )
        preview_full = self.controller.add_collateral_health_preview(
            collateral, user, True
        )

        self.add_collateral(user, collateral)
        self.assert_health_matches_preview(user, preview, False)
        self.assert_health_matches_preview(user, preview_full, True)
        event("stateful:add_collateral")
        event("stateful:health_preview:add_collateral")

    @precondition(lambda self: len(self.users) > 0)
    @rule(data=data())
    def borrow_more_with_health_preview(self, data):
        note("[BORROW MORE HEALTH PREVIEW]")
        user = data.draw(sampled_from(self.users), label="health_preview_borrow_user")
        assume(self.controller.health(user, False) > 0)

        _collateral, _x, _debt, N = self.controller.user_state(user)
        d_collateral, d_debt = data.draw(
            loan_increments_for_borrow_more(self.controller, user, N),
            label="health_preview_borrow_more_increments",
        )

        preview = self.controller.borrow_more_health_preview(
            d_collateral, d_debt, user, False
        )
        preview_full = self.controller.borrow_more_health_preview(
            d_collateral, d_debt, user, True
        )

        self.borrow_more(user, d_collateral, d_debt)
        self.assert_health_matches_preview(user, preview, False)
        self.assert_health_matches_preview(user, preview_full, True)
        event("stateful:health_preview:borrow_more")


class InterestAndCapsStateful(ControllerStateful):
    rate = integers(min_value=0, max_value=10**18 // (365 * 86400))
    cap_multiplier_bps = integers(min_value=0, max_value=20_000)

    @rule(rate=rate)
    def change_rate_and_time(self, rate):
        note("[CHANGE RATE]")
        before = {user: int(self.controller.debt(user)) for user in self.users}
        self.set_rate(rate)
        boa.env.time_travel(3600)
        self.controller.save_rate()

        for user, debt_before in before.items():
            assert self.controller.debt(user) >= debt_before
        event("stateful:rate_change")

    @rule(multiplier_bps=cap_multiplier_bps)
    def change_borrow_cap(self, multiplier_bps):
        note("[CHANGE BORROW CAP]")
        total_debt = int(self.controller.total_debt())
        available = int(self.controller.available_balance())
        cap = (total_debt + available) * multiplier_bps // 10_000
        self.set_borrow_cap(cap)
        assert self.controller.borrow_cap() == cap
        event("stateful:borrow_cap_change")
        if cap < total_debt:
            event("stateful:borrow_cap_change:below_debt")

    @invariant()
    def sum_of_debts(self):
        summed = sum(int(self.controller.debt(user)) for user in self.users)
        total = int(self.controller.total_debt())
        assert abs(summed - total) <= 100


TestHealthPreview = HealthPreviewStateful.TestCase
TestInterestAndCaps = InterestAndCapsStateful.TestCase
