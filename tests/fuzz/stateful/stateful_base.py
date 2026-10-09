import boa
from hypothesis import assume, event, note
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)
from hypothesis.strategies import integers, just, one_of

from tests.fuzz.strategies import lend_markets
from tests.utils import max_approve
from tests.utils.constants import MAX_UINT256, MIN_ASSETS, WAD
from tests.utils.deployers import ERC20_MOCK_DEPLOYER


class LlamalendStatefulBase(RuleBasedStateMachine):
    """
    Base state machine for Llamalend markets.

    Rules should call these wrappers instead of mutating controller state
    directly, so the on-chain state and the local model stay in sync.
    """

    @initialize(market=lend_markets())
    def initialize(self, market):
        self.initialize_market(market)
        self.initialize_vault(market)
        event("stateful:initialize")

    def initialize_market(self, market):
        self.controller = market["controller"]
        self.amm = market["amm"]
        self.price_oracle = market["price_oracle"]
        self.admin = market["admin"]
        self.configurator = market.get("configurator")
        self.monetary_policy = market.get("monetary_policy")
        self.users = []
        self.seen_borrowers = set()
        self.next_borrower_id = 0
        self.target_amm_volume = 0
        self.target_max_active_band_move = 0
        self.target_max_oracle_jump_bps = 0
        self.collateral_token = ERC20_MOCK_DEPLOYER.at(
            self.controller.collateral_token()
        )
        self.borrowed_token = ERC20_MOCK_DEPLOYER.at(self.controller.borrowed_token())
        self.borrowed_token.approve(self.controller.address, MAX_UINT256)

    def initialize_vault(self, market):
        self.vault = market["vault"]
        self.vault_users = []
        self.seen_vault_users = set()
        self.next_vault_user_id = 0
        self.vault_borrowed_token = ERC20_MOCK_DEPLOYER.at(self.vault.borrowed_token())

    # ---------------- controller actions ----------------

    def new_borrower(self, prefix: str = "user"):
        label = f"{prefix}_{self.next_borrower_id}"
        self.next_borrower_id += 1
        return label, boa.env.generate_address(label)

    def new_vault_user(self, prefix: str = "vault_user"):
        label = f"{prefix}_{self.next_vault_user_id}"
        self.next_vault_user_id += 1
        return label, boa.env.generate_address(label)

    def create_loan(self, user: str, collateral: int, debt: int, N: int):
        boa.deal(self.collateral_token, user, collateral)
        with boa.env.prank(user):
            self.collateral_token.approve(self.controller.address, MAX_UINT256)
            self.controller.create_loan(collateral, debt, N)

        if user not in self.users:
            self.users.append(user)
        self.seen_borrowers.add(user)

    def repay(self, user: str, repay_amount: int):
        boa.deal(self.borrowed_token, user, repay_amount)
        with boa.env.prank(user):
            self.borrowed_token.approve(self.controller.address, MAX_UINT256)
            self.controller.repay(repay_amount)

        if not self.controller.loan_exists(user) and user in self.users:
            self.users.remove(user)

    def borrow_more(self, user: str, d_collateral: int, d_debt: int):
        boa.deal(self.collateral_token, user, d_collateral)
        with boa.env.prank(user):
            self.collateral_token.approve(self.controller.address, MAX_UINT256)
            self.controller.borrow_more(d_collateral, d_debt)

    def add_collateral(self, user: str, d_collateral: int):
        boa.deal(self.collateral_token, user, d_collateral)
        with boa.env.prank(user):
            self.collateral_token.approve(self.controller.address, MAX_UINT256)
            self.controller.add_collateral(d_collateral, user)

    def remove_collateral(self, user: str, d_collateral: int):
        with boa.env.prank(user):
            self.controller.remove_collateral(d_collateral)

    def set_borrow_cap(self, borrow_cap: int):
        assert self.configurator is not None
        self.configurator.set_borrow_cap(self.controller, borrow_cap, sender=self.admin)

    def set_rate(self, rate: int):
        assert self.monetary_policy is not None
        self.monetary_policy.set_rate(rate)

    def record_active_band_move(self, before: int, after: int):
        self.target_max_active_band_move = max(
            self.target_max_active_band_move, abs(after - before)
        )

    def record_oracle_jump(self, before: int, after: int):
        if before == 0:
            return
        jump_bps = abs(after - before) * 10_000 // before
        self.target_max_oracle_jump_bps = max(self.target_max_oracle_jump_bps, jump_bps)

    def record_amm_volume(self, i: int, amount: int):
        if i == 0:
            borrowed_decs = int(self.borrowed_token.decimals())
            self.target_amm_volume += amount * 10 ** (18 - borrowed_decs)
            return

        collateral_decs = int(self.collateral_token.decimals())
        price = int(self.amm.price_oracle())
        self.target_amm_volume += amount * 10 ** (18 - collateral_decs) * price // WAD

    def liquidate_unhealthy_users(self):
        positions = self.controller.users_to_liquidate(0, len(self.users))
        if len(positions) == 0:
            event("stateful:liquidate:none")
            return

        note("[HARD LIQUIDATE]")
        event("stateful:liquidate")
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

    def withdraw_amounts(self, user: str):
        max_withdraw = int(self.vault.maxWithdraw(user))
        total_assets = int(self.vault.totalAssets())
        assume(max_withdraw > 0)

        strategies = []
        partial_max = min(max_withdraw, max(total_assets - MIN_ASSETS, 0))
        if partial_max > 0:
            strategies.append(integers(min_value=1, max_value=partial_max))
        if max_withdraw == total_assets:
            strategies.append(just(max_withdraw))

        assume(len(strategies) > 0)
        if len(strategies) == 1:
            return strategies[0]
        return one_of(*strategies)

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

        if self.vault.balanceOf(user) > 0 and user not in self.vault_users:
            self.vault_users.append(user)
        self.seen_vault_users.add(user)

    def mint_vault_shares(self, user: str, shares: int):
        assets = self.vault.previewMint(shares)
        boa.deal(self.vault_borrowed_token, user, assets)
        with boa.env.prank(user):
            max_approve(self.vault_borrowed_token, self.vault.address)
            self.vault.mint(shares, user)

        if self.vault.balanceOf(user) > 0 and user not in self.vault_users:
            self.vault_users.append(user)
        self.seen_vault_users.add(user)

    def withdraw_from_vault(self, user: str, amount: int):
        self.vault.withdraw(amount, user, sender=user)
        if self.vault.balanceOf(user) == 0 and user in self.vault_users:
            self.vault_users.remove(user)

    def redeem_vault_shares(self, user: str, shares: int):
        self.vault.redeem(shares, user, sender=user)
        if self.vault.balanceOf(user) == 0 and user in self.vault_users:
            self.vault_users.remove(user)

    # ---------------- local model helpers ----------------

    def sync_users(self):
        n = self.controller.n_loans()
        self.users = [self.controller.loans(i) for i in range(n)]

    def open_users(self):
        n = self.controller.n_loans()
        return [self.controller.loans(i) for i in range(n)]

    # ---------------- invariants ----------------

    @rule()
    def time_forward(self):
        event("stateful:time_forward")
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
        assert len(self.users) == len(set(self.users))
        for user in self.users:
            assert self.controller.loan_exists(user)

    @invariant()
    def vault_users_invariant(self):
        assert len(self.vault_users) == len(set(self.vault_users))
        for user in self.vault_users:
            assert self.vault.balanceOf(user) > 0
        for user in self.seen_vault_users:
            assert (self.vault.balanceOf(user) > 0) == (user in self.vault_users)

    @precondition(lambda self: len(self.users) > 0)
    @rule()
    def liquidate(self):
        self.liquidate_unhealthy_users()


TestBase = LlamalendStatefulBase.TestCase
