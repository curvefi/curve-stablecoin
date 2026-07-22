import boa
from hypothesis import assume, event, note
from hypothesis.stateful import precondition, rule
from hypothesis.strategies import data, integers, sampled_from

from tests.fuzz.stateful.stateful_base import LlamalendStatefulBase
from tests.fuzz.strategies import (
    loan_amounts_for_create,
    loan_increments_for_borrow_more,
    ticks,
)


class CreateLoanStateful(LlamalendStatefulBase):
    @rule(N=ticks, data=data())
    def create_loan_rule(self, N, data):
        note("[CREATE LOAN]")
        user_label, user = self.new_borrower("user")

        collateral, debt = data.draw(
            loan_amounts_for_create(self.controller, N),
            label=f"loan_amounts_for_create({user_label})",
        )

        note(
            f"creating loan: N={N}, user={user_label}, collateral={collateral}, debt={debt}, "
            f"collat_decs={self.collateral_token.decimals()}, loan_discount={self.controller.loan_discount()}"
        )
        event("stateful:create_loan")
        self.create_loan(user, collateral, debt, N)


class CreateRepayStateful(CreateLoanStateful):
    @precondition(lambda self: len(self.users) > 0)
    @rule(data=data())
    def repay_rule(self, data):
        note("[REPAY]")
        user = data.draw(sampled_from(self.users), label="repay_user")

        debt = self.controller.debt(user)
        assume(debt > 0)
        repay_amount = data.draw(
            integers(min_value=1, max_value=debt), label="repay_amount"
        )

        self.repay(user, repay_amount)
        event("stateful:repay")
        if repay_amount == debt:
            event("stateful:repay:full")
        else:
            event("stateful:repay:partial")
        note(f"repay: user={user}, debt_before={debt}, repay_amount={repay_amount}")


class BorrowMoreStateful(CreateRepayStateful):
    @precondition(lambda self: len(self.users) > 0)
    @rule(data=data())
    def borrow_more_rule(self, data):
        note("[BORROW MORE]")
        user = data.draw(sampled_from(self.users), label="borrow_more_user")
        assume(self.controller.health(user, False) > 0)

        _collateral, _x, _debt, N = self.controller.user_state(user)
        d_collateral, d_debt = data.draw(
            loan_increments_for_borrow_more(self.controller, user, N),
            label="borrow_more_increments",
        )

        self.borrow_more(user, d_collateral, d_debt)
        event("stateful:borrow_more")


class ControllerStateful(BorrowMoreStateful):
    @precondition(lambda self: len(self.users) > 0)
    @rule(data=data())
    def remove_collateral_rule(self, data):
        note("[REMOVE COLLATERAL]")
        user = data.draw(sampled_from(self.users), label="remove_collateral_user")

        collateral, _x, debt, N = self.controller.user_state(user)
        min_coll = self.controller.min_collateral(debt, N, user)
        if collateral <= min_coll:
            event("stateful:remove_collateral:none")
            return
        removable = collateral - min_coll

        if removable == 0:
            event("stateful:remove_collateral:none")
            return

        min_remove = max(1, removable // 64)
        d_collateral = data.draw(
            integers(min_value=min_remove, max_value=removable),
            label="remove_collateral_amount",
        )

        self.remove_collateral(user, d_collateral)
        event("stateful:remove_collateral")


TestCreateLoan = CreateLoanStateful.TestCase
TestCreateRepay = CreateRepayStateful.TestCase
TestBorrowMore = BorrowMoreStateful.TestCase
TestControllerStateful = ControllerStateful.TestCase
