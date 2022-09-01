"""
Stateful test to create and repay loans without moving the price oracle
"""
import brownie
from datetime import timedelta
from brownie.test import strategy


class StatefulLendBorrow:
    n = strategy('int256', min_value=5, max_value=50)
    amount = strategy('uint256')
    c_amount = strategy('uint256')
    user = strategy('address')

    def __init__(self, controller_factory, amm, controller, collateral_token, borrowed_token, accounts):
        self.amm = amm
        self.controller = controller
        self.collateral = collateral_token
        self.stablecoin = borrowed_token
        self.accounts = accounts
        self.debt_ceiling = controller_factory.debt_ceiling(controller)
        for u in accounts:
            collateral_token.approve(controller, 2**256-1, {'from': u})
            borrowed_token.approve(controller, 2**256-1, {'from': u})

    def rule_create_loan(self, c_amount, amount, n, user):
        if self.controller.loan_exists(user):
            with brownie.reverts('Loan already created'):
                self.controller.create_loan(c_amount, amount, n, {'from': user})
            return

        too_high = False
        try:
            self.controller.calculate_debt_n1(c_amount, amount, n)
        except Exception as e:
            too_high = str(e) == 'revert: Debt too high'
        if too_high:
            with brownie.reverts('Debt too high'):
                self.controller.create_loan(c_amount, amount, n, {'from': user})
            return

        if self.controller.total_debt() + amount > self.debt_ceiling:
            if (
                    (self.controller.total_debt() + amount) * self.amm.get_rate_mul() > 2**256 - 1
                    or c_amount * self.amm.get_p() > 2**256 - 1
            ):
                with brownie.reverts():
                    self.controller.create_loan(c_amount, amount, n, {'from': user})
            else:
                with brownie.reverts():  # Dept ceiling or too deep
                    self.controller.create_loan(c_amount, amount, n, {'from': user})
            return

        if amount == 0:
            with brownie.reverts('No loan'):
                self.controller.create_loan(c_amount, amount, n, {'from': user})
                # It's actually division by zero which happens
            return

        try:
            self.collateral._mint_for_testing(user, c_amount, {'from': user})
        except Exception:
            return  # Probably overflow

        if c_amount >= 2**128:
            with brownie.reverts():
                self.controller.create_loan(c_amount, amount, n, {'from': user})
            return

        if c_amount // n <= 100:
            with brownie.reverts():
                # Amount too low or too deep
                self.controller.create_loan(c_amount, amount, n, {'from': user})
            return

        try:
            self.controller.create_loan(c_amount, amount, n, {'from': user})
        except Exception as e:
            if 'Too deep' not in str(e):
                raise

    def rule_repay(self, amount, user):
        if amount == 0:
            self.controller.repay(amount, user, {'from': user})
            return
        if not self.controller.loan_exists(user):
            with brownie.reverts("Loan doesn't exist"):
                self.controller.repay(amount, user, {'from': user})
            return
        self.controller.repay(amount, user, {'from': user})

    def rule_add_collateral(self, c_amount, user):
        if c_amount == 0:
            self.controller.add_collateral(c_amount, user, {'from': user})
            return

        try:
            self.collateral._mint_for_testing(user, c_amount, {'from': user})
        except Exception:
            return  # Probably overflow

        if not self.controller.loan_exists(user):
            with brownie.reverts("Loan doesn't exist"):
                self.controller.add_collateral(c_amount, user, {'from': user})
            return

        if (c_amount + self.amm.get_sum_xy(user)[1]) * self.amm.get_p() > 2**256 - 1:
            with brownie.reverts():
                self.controller.add_collateral(c_amount, user, {'from': user})
            return

        self.controller.add_collateral(c_amount, user, {'from': user})

    def rule_borrow_more(self, c_amount, amount, user):
        try:
            self.collateral._mint_for_testing(user, c_amount, {'from': user})
        except Exception:
            return  # Probably overflow

        if amount == 0:
            self.controller.borrow_more(c_amount, amount, {'from': user})
            return

        if not self.controller.loan_exists(user):
            with brownie.reverts("Loan doesn't exist"):
                self.controller.borrow_more(c_amount, amount, {'from': user})
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
            too_high = str(e) == 'revert: Debt too high'
        if too_high:
            with brownie.reverts('Debt too high'):
                self.controller.borrow_more(c_amount, amount, {'from': user})
            return

        if self.controller.total_debt() + amount > self.debt_ceiling:
            if (self.controller.total_debt() + amount) * self.amm.get_rate_mul() > 2**256 - 1:
                with brownie.reverts():
                    self.controller.borrow_more(c_amount, amount, {'from': user})
            else:
                with brownie.reverts():
                    self.controller.borrow_more(c_amount, amount, {'from': user})
            return

        if final_collateral * self.amm.get_p() > 2**256 - 1:
            with brownie.reverts():
                self.controller.borrow_more(c_amount, amount, {'from': user})
            return

        self.controller.borrow_more(c_amount, amount, {'from': user})

    def invariant_debt_supply(self):
        assert self.controller.total_debt() == self.stablecoin.totalSupply() - self.stablecoin.balanceOf(self.controller)

    def invariant_sum_of_debts(self):
        assert sum(self.controller.debt(u) for u in self.accounts) == self.controller.total_debt()

    def invariant_health(self):
        for user in self.accounts:
            if self.controller.loan_exists(user):
                assert self.controller.health(user) > 0


def test_stateful_lendborrow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts, state_machine):
    state_machine(StatefulLendBorrow, controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts,
                  settings={'max_examples': 50, 'stateful_step_count': 20, 'deadline': timedelta(seconds=1000)})


def test_bad_health_underflow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts, state_machine):
    state = StatefulLendBorrow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts)
    state.rule_create_loan(amount=1, c_amount=21, n=6, user=accounts[0])
    state.invariant_health()


def test_overflow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts, state_machine):
    state = StatefulLendBorrow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts)
    state.rule_create_loan(
        amount=407364794483206832621538773467837164307398905518629081113581615337081836,
        c_amount=41658360764272065869638360137931952069431923873907374062, n=5, user=accounts[0])


def test_health_overflow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts, state_machine):
    state = StatefulLendBorrow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts)
    state.rule_create_loan(amount=256, c_amount=2787635851270792912435800128182537894764544, n=5, user=accounts[0])
    state.invariant_health()


def test_health_underflow_2(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts, state_machine):
    state = StatefulLendBorrow(controller_factory, market_amm, market_controller, collateral_token, stablecoin, accounts)
    state.rule_create_loan(amount=1, c_amount=44, n=6, user=accounts[0])
    state.invariant_health()
