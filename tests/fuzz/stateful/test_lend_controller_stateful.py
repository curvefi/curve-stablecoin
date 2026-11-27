import boa
from hypothesis import assume, event, note
from hypothesis.stateful import precondition, rule
from hypothesis.strategies import data, integers, sampled_from

from tests.fuzz.stateful.test_controller_stateful import ControllerStateful


class LendDepositStateful(ControllerStateful):
    @precondition(lambda self: self.vault.maxSupply() > self.vault.totalAssets())
    @rule(data=data())
    def deposit(self, data):
        note("[DEPOSIT]")
        user_label, user = self.new_vault_user("vault_user")

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
        event("stateful:deposit")


class LendControllerStateful(LendDepositStateful):
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
            self.withdraw_amounts(user),
            label=f"withdraw_amount({user})",
        )

        note(f"withdrawing: user={user}, amount={amount}, shares={user_shares}")
        self.withdraw_from_vault(user, amount)
        event("stateful:withdraw")


TestLendDeposit = LendDepositStateful.TestCase
TestLendControllerStateful = LendControllerStateful.TestCase
