import boa

from tests.fuzz.stateful.test_controller_stateful import ControllerStateful
from tests.fuzz.strategies import lend_markets

from hypothesis import note, assume
from hypothesis.strategies import data, integers, sampled_from
from hypothesis.stateful import rule, initialize, precondition


class LendControllerStateful(ControllerStateful):
    @initialize(market=lend_markets())
    def _initialize(self, market):
        self.initialize_market(market)
        self.initialize_vault(market)

    @precondition(lambda self: self.vault.maxSupply() > self.vault.totalAssets())
    @rule(data=data())
    def deposit(self, data):
        note("[DEPOSIT]")
        user_label = f"vault_user_{len(self.vault_users)}"
        user = boa.env.generate_address(user_label)

        vault = self.vault
        max_deposit = int(vault.maxDeposit(user))
        assume(max_deposit > 0)

        min_required = self.min_vault_deposit()
        token_decimals = int(self.vault_borrowed_token.decimals())
        upper_bound = min(max_deposit, 10**6 * 10**token_decimals)
        assume(min_required <= upper_bound)

        amount = data.draw(
            integers(min_value=min_required, max_value=upper_bound),
            label=f"deposit_amount({user_label})",
        )

        note(
            f"depositing: user={user_label}, amount={amount}, max_deposit={max_deposit}"
        )

        self.deposit_to_vault(user, amount)

    @precondition(lambda self: self.users_allowed_to_withdraw())
    @rule(data=data())
    def withdraw(self, data):
        note("[WITHDRAW]")
        vault = self.vault
        user = data.draw(
            sampled_from(self.users_allowed_to_withdraw()), label="withdraw_user"
        )

        user_shares = vault.balanceOf(user)

        amount = data.draw(
            integers(min_value=1, max_value=min(user_shares, vault.maxWithdraw(user))),
            label=f"withdraw_amount({user})",
        )

        note(f"withdrawing: user={user}, amount={amount}, shares={user_shares}")
        self.withdraw_from_vault(user, amount)


TestLendControllerStateful = LendControllerStateful.TestCase
