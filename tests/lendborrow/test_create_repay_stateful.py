"""
Stateful test to create and repay loans without moving the price oracle
"""
import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant


class StatefulLendBorrow(RuleBasedStateMachine):
    n = st.integers(min_value=5, max_value=50)
    amount = st.integers(min_value=0, max_value=2**256-1)
    c_amount = st.integers(min_value=0, max_value=2**256-1)
    user_id = st.integers(min_value=0, max_value=9)

    def __init__(self):
        super().__init__()
        self.controller = self.market_controller
        self.amm = self.market_amm
        self.debt_ceiling = self.controller_factory.debt_ceiling(self.controller)
        for u in self.accounts:
            with boa.env.prank(u):
                self.collateral_token.approve(self.controller, 2**256-1)
                self.stablecoin.approve(self.controller, 2**256-1)

    @rule(c_amount=c_amount, amount=amount, n=n, user_id=user_id)
    def create_loan(self, c_amount, amount, n, user_id):
        user = self.accounts[user_id]

        with boa.env.prank(user):
            if self.controller.loan_exists(user):
                with boa.reverts('Loan already created'):
                    self.controller.create_loan(c_amount, amount, n)
                return

            too_high = False
            try:
                self.controller.calculate_debt_n1(c_amount, amount, n)
            except Exception as e:
                too_high = 'Debt too high' in str(e)
            if too_high:
                with boa.reverts('Debt too high'):
                    self.controller.create_loan(c_amount, amount, n)
                return

            if self.controller.total_debt() + amount > self.debt_ceiling:
                if (
                        (self.controller.total_debt() + amount) * self.amm.get_rate_mul() > 2**256 - 1
                        or c_amount * self.amm.get_p() > 2**256 - 1
                ):
                    with boa.reverts():
                        self.controller.create_loan(c_amount, amount, n)
                else:
                    with boa.reverts():  # Dept ceiling or too deep
                        self.controller.create_loan(c_amount, amount, n)
                return

            if amount == 0:
                with boa.reverts('No loan'):
                    self.controller.create_loan(c_amount, amount, n)
                    # It's actually division by zero which happens
                return

            try:
                self.collateral_token._mint_for_testing(user, c_amount)
            except Exception:
                return  # Probably overflow

            if c_amount // n >= 2**128:
                with boa.reverts():
                    self.controller.create_loan(c_amount, amount, n)
                return

            if c_amount // n <= 100:
                with boa.reverts():
                    # Amount too low or too deep
                    self.controller.create_loan(c_amount, amount, n)
                return

            try:
                self.controller.create_loan(c_amount, amount, n)
            except Exception as e:
                if 'Too deep' not in str(e):
                    raise

    @rule(amount=amount, user_id=user_id)
    def repay(self, amount, user_id):
        user = self.accounts[user_id]
        with boa.env.prank(user):
            if amount == 0:
                self.controller.repay(amount, user)
                return
            if not self.controller.loan_exists(user):
                with boa.reverts("Loan doesn't exist"):
                    self.controller.repay(amount, user)
                return
            self.controller.repay(amount, user)

    @rule(c_amount=c_amount, user_id=user_id)
    def add_collateral(self, c_amount, user_id):
        user = self.accounts[user_id]

        with boa.env.prank(user):
            if c_amount == 0:
                self.controller.add_collateral(c_amount, user)
                return

            try:
                self.collateral_token._mint_for_testing(user, c_amount)
            except Exception:
                return  # Probably overflow

            if not self.controller.loan_exists(user):
                with boa.reverts("Loan doesn't exist"):
                    self.controller.add_collateral(c_amount, user)
                return

            if (c_amount + self.amm.get_sum_xy(user)[1]) * self.amm.get_p() > 2**256 - 1:
                with boa.reverts():
                    self.controller.add_collateral(c_amount, user)
                return

            self.controller.add_collateral(c_amount, user)

    @rule(c_amount=c_amount, amount=amount, user_id=user_id)
    def borrow_more(self, c_amount, amount, user_id):
        user = self.accounts[user_id]

        with boa.env.prank(user):
            try:
                self.collateral_token._mint_for_testing(user, c_amount)
            except Exception:
                return  # Probably overflow

            if amount == 0:
                self.controller.borrow_more(c_amount, amount)
                return

            if not self.controller.loan_exists(user):
                with boa.reverts("Loan doesn't exist"):
                    self.controller.borrow_more(c_amount, amount)
                return

            final_debt = self.controller.debt(user) + amount
            x, y = self.amm.get_sum_xy(user)
            assert x == 0
            final_collateral = y + c_amount
            n1, n2 = self.amm.read_user_tick_numbers(user)
            n = n2 - n1 + 1

            too_high = False
            try:
                self.controller.calculate_debt_n1(final_collateral, final_debt, n)
            except Exception as e:
                too_high = 'Debt too high' in str(e)
            if too_high:
                with boa.reverts('Debt too high'):
                    self.controller.borrow_more(c_amount, amount)
                return

            if self.controller.total_debt() + amount > self.debt_ceiling:
                if (self.controller.total_debt() + amount) * self.amm.get_rate_mul() > 2**256 - 1:
                    with boa.reverts():
                        self.controller.borrow_more(c_amount, amount)
                else:
                    with boa.reverts():
                        self.controller.borrow_more(c_amount, amount)
                return

            if final_collateral * self.amm.get_p() > 2**256 - 1:
                with boa.reverts():
                    self.controller.borrow_more(c_amount, amount)
                return

            self.controller.borrow_more(c_amount, amount)

    @invariant()
    def debt_supply(self):
        assert self.controller.total_debt() == self.stablecoin.totalSupply() - self.stablecoin.balanceOf(self.controller)

    @invariant()
    def sum_of_debts(self):
        assert sum(self.controller.debt(u) for u in self.accounts) == self.controller.total_debt()

    @invariant()
    def health(self):
        for user in self.accounts:
            if self.controller.loan_exists(user):
                assert self.controller.health(user) > 0


def test_stateful_lendborrow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts):
    StatefulLendBorrow.TestCase.settings = settings(max_examples=50, stateful_step_count=20)
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    run_state_machine_as_test(StatefulLendBorrow)


def test_bad_health_underflow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts):
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    with boa.env.anchor():
        state = StatefulLendBorrow()
        state.create_loan(amount=1, c_amount=21, n=6, user_id=0)
        state.health()


def test_overflow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts):
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    with boa.env.anchor():
        state = StatefulLendBorrow()
        state.create_loan(
            amount=407364794483206832621538773467837164307398905518629081113581615337081836,
            c_amount=41658360764272065869638360137931952069431923873907374062, n=5, user_id=0)


def test_health_overflow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts):
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    with boa.env.anchor():
        state = StatefulLendBorrow()
        state.create_loan(amount=256, c_amount=2787635851270792912435800128182537894764544, n=5, user_id=0)
        state.health()


def test_health_underflow_2(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts):
    for k, v in locals().items():
        setattr(StatefulLendBorrow, k, v)
    with boa.env.anchor():
        state = StatefulLendBorrow()
        state.create_loan(amount=1, c_amount=44, n=6, user_id=0)
        state.health()
