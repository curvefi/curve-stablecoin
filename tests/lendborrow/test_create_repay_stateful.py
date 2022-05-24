"""
Stateful test to create and repay loans without moving the price oracle
but with nonzero rate
"""
import brownie
from brownie import exceptions
from brownie.test import strategy


class StatefulLendBorrow:
    n = strategy('int256', min_value=5, max_value=50)
    amount = strategy('uint256', max_value=2 * 10**6 * 10**18)
    c_amount = strategy('uint256', max_value=10**9 * 10**18 // 3000)
    user_id = strategy('uint256', max_value=4)

    def __init__(self, amm, controller, collateral_token, borrowed_token, accounts):
        self.amm = amm
        self.controller = controller
        self.collateral = collateral_token
        self.stablecoin = borrowed_token
        self.accounts = accounts
        self.debt_ceiling = self.controller.debt_ceiling()

    def rule_create_loan(self, c_amount, amount, n, user_id):
        user = self.accounts[user_id]
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
            with brownie.reverts('Debt ceiling'):
                self.controller.create_loan(c_amount, amount, n, {'from': user})
            return

        if amount == 0:
            with brownie.reverts():
                self.controller.create_loan(c_amount, amount, n, {'from': user})
                # It's actually division by zero which happens
            return

        self.collateral._mint_for_testing(user, c_amount, {'from': user})
        try:
            self.controller.create_loan(c_amount, amount, n, {'from': user})
        except exceptions.VirtualMachineError as e:
            if str(e) == 'revert: Amount too low':
                assert c_amount < 10**6
            else:
                raise

    def rule_repay(self, amount, user_id):
        pass

    def rule_add_collateral(self, c_amount, user_id):
        pass

    def rule_borrow_more(self, c_amount, amount, user_id):
        pass


def test_stateful_lendborrow(market_amm, market_controller, collateral_token, stablecoin, accounts, state_machine):
    state_machine(StatefulLendBorrow, market_amm, market_controller, collateral_token, stablecoin, accounts)
