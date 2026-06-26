import boa
from hypothesis import note
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition

from tests.utils import max_approve
from tests.utils.constants import MAX_UINT256, MIN_ASSETS, WAD
from tests.utils.deployers import ERC20_MOCK_DEPLOYER, STABLECOIN_DEPLOYER


class LlamalendStatefulBase(RuleBasedStateMachine):
    """
    Base state machine for Llamalend markets.

    Rules should call these wrappers instead of mutating controller state
    directly, so the on-chain state and the local model stay in sync.
    """

    def initialize_market(self, market):
        self.controller = market["controller"]
        self.amm = market["amm"]
        self.users = []
        self.collateral_token = ERC20_MOCK_DEPLOYER.at(
            self.controller.collateral_token()
        )
        self.borrowed_token = STABLECOIN_DEPLOYER.at(self.controller.borrowed_token())
        self.borrowed_token.approve(self.controller.address, MAX_UINT256)

    def initialize_vault(self, market):
        self.vault = market["vault"]
        self.vault_users = []
        self.vault_borrowed_token = ERC20_MOCK_DEPLOYER.at(self.vault.borrowed_token())

    # ---------------- controller actions ----------------

    def create_loan(self, user: str, collateral: int, debt: int, N: int):
        boa.deal(self.collateral_token, user, collateral)
        with boa.env.prank(user):
            self.collateral_token.approve(self.controller.address, MAX_UINT256)
            self.controller.create_loan(collateral, debt, N)

        self.users.append(user)

    def repay(self, user: str, repay_amount: int):
        boa.deal(self.borrowed_token, user, repay_amount)
        with boa.env.prank(user):
            self.borrowed_token.approve(self.controller.address, MAX_UINT256)
            self.controller.repay(repay_amount)

        if not self.controller.loan_exists(user):
            self.users.remove(user)

    def borrow_more(self, user: str, d_collateral: int, d_debt: int):
        boa.deal(self.collateral_token, user, d_collateral)
        with boa.env.prank(user):
            self.collateral_token.approve(self.controller.address, MAX_UINT256)
            self.controller.borrow_more(d_collateral, d_debt)

    def remove_collateral(self, user: str, d_collateral: int):
        with boa.env.prank(user):
            self.controller.remove_collateral(d_collateral)

    def liquidate_unhealthy_users(self):
        positions = self.controller.users_to_liquidate(0, len(self.users))
        if len(positions) == 0:
            return

        note("[HARD LIQUIDATE]")
        for pos in positions:
            note(
                f"liquidating user {pos.user} with health {self.controller.health(pos.user, True)}"
            )
            required = self.controller.tokens_to_liquidate(pos.user, WAD)
            if required > 0:
                boa.deal(self.borrowed_token, boa.env.eoa, required)
            self.controller.liquidate(pos.user, 0, WAD)

        assert len(self.controller.users_to_liquidate(0, len(self.users))) == 0
        self.sync_users()

    # ---------------- vault actions ----------------

    def users_allowed_to_withdraw(self):
        return [user for user in self.vault_users if self.vault.maxWithdraw(user) > 0]

    def min_vault_deposit(self) -> int:
        current_assets = int(self.vault.totalAssets())
        if current_assets >= MIN_ASSETS:
            return 1
        return MIN_ASSETS - current_assets

    def deposit_to_vault(self, user: str, amount: int):
        boa.deal(self.vault_borrowed_token, user, amount)
        with boa.env.prank(user):
            max_approve(self.vault_borrowed_token, self.vault.address)
            self.vault.deposit(amount, user)

        self.vault_users.append(user)

    def withdraw_from_vault(self, user: str, amount: int):
        user_shares = self.vault.balanceOf(user)
        self.vault.withdraw(amount, user, sender=user)
        if amount == user_shares:
            self.vault_users.remove(user)

    # ---------------- local model helpers ----------------

    def sync_users(self):
        n = self.controller.n_loans()
        self.users = [self.controller.loans(i) for i in range(n)]

    def open_users(self):
        n = self.controller.n_loans()
        return [self.controller.loans(i) for i in range(n)]

    # ---------------- invariants ----------------

    @invariant()
    def time_passes(self):
        before = {u: self.controller.debt(u) for u in self.users}

        boa.env.time_travel(3600)
        self.controller.save_rate()

        for u, d0 in before.items():
            assert self.controller.debt(u) >= d0

    @invariant()
    def open_users_invariant(self):
        onchain_users = self.open_users()
        assert set(onchain_users) == set(self.users)
        assert len(onchain_users) == len(self.users)
        for user in self.users:
            assert self.controller.loan_exists(user)

    @precondition(lambda self: len(self.users) > 0)
    @invariant()
    def liquidate(self):
        self.liquidate_unhealthy_users()


TestBase = LlamalendStatefulBase.TestCase
