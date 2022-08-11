import brownie
from brownie.test import strategy


class StatefulLendBorrow:
    n = strategy('int256', min_value=5, max_value=50)
    amount = strategy('uint256')
    c_amount = strategy('uint256')
    user = strategy('address')
    t = strategy('uint256', max_value=86400 * 365)
    rate = strategy('uint256', max_value=2**255 - 1)  # Negative is probably not good btw

    def __init__(self, controller_factory, chain, amm, controller, monetary_policy, collateral_token, borrowed_token, accounts):
        self.chain = chain
        self.monetary_policy = monetary_policy
        self.amm = amm
        self.controller = controller
        self.collateral = collateral_token
        self.stablecoin = borrowed_token
        self.accounts = accounts
        self.debt_ceiling = controller_factory.debt_ceiling(controller)
        for u in accounts:
            collateral_token.approve(controller, 2**256-1, {'from': u})
            borrowed_token.approve(controller, 2**256-1, {'from': u})
        monetary_policy.set_rate(int(1e18 * 0.04 / 365 / 86400), {'from': accounts[0]})

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
                    (self.controller.total_debt() + amount) * self.amm.rate_mul() > 2**256 - 1
                    or c_amount * self.amm.get_p() > 2**256 - 1
            ):
                with brownie.reverts():
                    self.controller.create_loan(c_amount, amount, n, {'from': user})
            else:
                with brownie.reverts():
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
            try:
                self.controller.create_loan(c_amount, amount, n, {'from': user})
            except Exception as e:
                if ('Too deep' in str(e) and c_amount * 3000 / amount < 1e-3) or 'Amount too low' in str(e):
                    return
                else:
                    raise

        try:
            self.controller.create_loan(c_amount, amount, n, {'from': user})
        except Exception as e:
            if 'Too deep' in str(e) and c_amount * 3000 / amount < 1e-3:
                pass
            else:
                raise

    def rule_repay(self, amount, user):
        if amount == 0:
            self.controller.repay(amount, user, {'from': user})
            return

        if not self.controller.loan_exists(user):
            with brownie.reverts("Loan doesn't exist"):
                self.controller.repay(amount, user, {'from': user})
            return

        # When we have interest - need to have admin fees claimed to have enough in circulation
        self.controller.collect_fees({'from': user})
        # And we need to transfer them to us if necessary
        diff = self.controller.debt(user) - self.stablecoin.balanceOf(user)
        if diff > 0:
            self.stablecoin.transfer(user, diff, {'from': self.accounts[1]})

        self.controller.repay(amount, user, {'from': user})

    def rule_add_collateral(self, c_amount, user):
        try:
            self.collateral._mint_for_testing(user, c_amount, {'from': user})
        except Exception:
            return  # Probably overflow

        if c_amount == 0:
            self.controller.add_collateral(c_amount, user, {'from': user})
            return

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
        if amount == 0:
            self.controller.borrow_more(c_amount, amount, {'from': user})
            return

        try:
            self.collateral._mint_for_testing(user, c_amount, {'from': user})
        except Exception:
            return  # Probably overflow

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
            if (self.controller.total_debt() + amount) * self.amm.rate_mul() > 2**256 - 1:
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

    def rule_time_travel(self, t):
        self.chain.sleep(t)

    def rule_change_rate(self, rate):
        self.monetary_policy.set_rate(rate, {'from': self.accounts[0]})

    def invariant_sum_of_debts(self):
        assert abs(sum(self.controller.debt(u) for u in self.accounts) - self.controller.total_debt()) <= len(self.accounts)

    def invariant_debt_payable(self):
        tx = self.controller.collect_fees({'from': self.accounts[0]})
        supply = self.stablecoin.totalSupply(block_identifier=tx.block_number)
        b = self.stablecoin.balanceOf(self.controller, block_identifier=tx.block_number)
        debt = self.controller.total_debt(block_identifier=tx.block_number)
        assert debt == supply - b


def test_stateful_lendborrow(controller_factory, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, state_machine):
    state_machine(StatefulLendBorrow, controller_factory, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts,
                  settings={'max_examples': 100, 'stateful_step_count': 10})


def test_rate_too_high(controller_factory, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, state_machine):
    state = StatefulLendBorrow(
        controller_factory, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts)
    state.rule_change_rate(rate=19298681539552733520784193015473224553355594960504706685844695763378761203935)
    state.rule_time_travel(100000)
    # rate clipping
    state.amm.get_rate_mul()


def test_unexpected_revert(controller_factory, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, state_machine):
    state = StatefulLendBorrow(
        controller_factory, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts)
    state.rule_create_loan(amount=28150, c_amount=5384530291638384907, n=8, user=accounts[1])
    state.rule_time_travel(t=31488)
    state.rule_repay(amount=39777, user=accounts[1])


def test_no_revert_reason(controller_factory, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, state_machine):
    state = StatefulLendBorrow(
        controller_factory, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts)
    state.rule_create_loan(amount=1, c_amount=1, n=5, user=accounts[0])


def test_too_deep(controller_factory, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts, state_machine):
    state = StatefulLendBorrow(
        controller_factory, chain, market_amm, market_controller, monetary_policy, collateral_token, stablecoin, accounts)
    state.rule_create_loan(amount=13119, c_amount=48, n=43, user=accounts[0])
    state.rule_create_loan(amount=34049, c_amount=48388, n=18, user=accounts[1])
    state.rule_create_loan(amount=10161325728155098164, c_amount=4156800770, n=50, user=accounts[2])
