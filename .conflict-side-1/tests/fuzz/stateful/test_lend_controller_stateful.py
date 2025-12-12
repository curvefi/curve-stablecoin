import boa
from tests.fuzz.stateful.test_controller_stateful import ControllerStateful
from tests.fuzz.strategies import lend_markets

from hypothesis import note, assume
from hypothesis.strategies import data, integers, sampled_from
from hypothesis.stateful import rule, initialize, precondition

from tests.utils.deployers import ERC20_MOCK_DEPLOYER
from tests.utils.constants import MIN_ASSETS
from tests.utils import max_approve


class LendControllerStateful(ControllerStateful):
    @initialize(market=lend_markets())
    def _initialize(self, market):
        super()._initialize(market)
        self.vault = market["vault"]
        self.vault_users = []

    def users_allowed_to_withdraw(self):
        return [user for user in self.vault_users if self.vault.maxWithdraw(user) > 0]

    @precondition(lambda self: self.vault.maxSupply() > self.vault.totalAssets())
    @rule(data=data())
    def deposit(self, data):
        note("[DEPOSIT]")
        user_label = f"vault_user_{len(self.vault_users)}"
        user = boa.env.generate_address(user_label)

        vault = self.vault
        max_deposit = int(vault.maxDeposit(user))
        assume(max_deposit > 0)

        current_assets = int(vault.totalAssets())
        min_required = (
            1 if current_assets >= MIN_ASSETS else MIN_ASSETS - current_assets
        )

        borrowed_token = ERC20_MOCK_DEPLOYER.at(vault.borrowed_token())  # type: ignore[attr-defined]
        token_decimals = int(borrowed_token.decimals())  # type: ignore[attr-defined]
        upper_bound = min(max_deposit, 10**6 * 10**token_decimals)
        assume(min_required <= upper_bound)

        amount = data.draw(
            integers(min_value=min_required, max_value=upper_bound),
            label=f"deposit_amount({user_label})",
        )

        note(
            f"depositing: user={user_label}, amount={amount}, max_deposit={max_deposit}"
        )

        boa.deal(borrowed_token, user, amount)
        with boa.env.prank(user):
            max_approve(borrowed_token, vault.address)
            vault.deposit(amount, user)

        self.vault_users.append(user)

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

        vault.withdraw(amount, user, sender=user)
        if amount == user_shares:
            self.vault_users.remove(user)


TestLendControllerStateful = LendControllerStateful.TestCase
