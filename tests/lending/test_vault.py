import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant


DEAD_SHARES = 1000


def test_vault_creation(vault, market_controller, market_amm, market_mpolicy):
    assert vault.amm() == market_amm.address
    assert vault.controller() == market_controller.address
    assert market_controller.monetary_policy() == market_mpolicy.address


def test_deposit_and_withdraw(vault, borrowed_token, accounts):
    one_token = 10 ** borrowed_token.decimals()
    amount = 10**6 * one_token
    user = accounts[1]
    borrowed_token._mint_for_testing(user, amount)

    with boa.env.prank(user):
        borrowed_token.approve(vault.address, 2**256-1)
        vault.deposit(amount)
        assert vault.totalAssets() == amount
        assert vault.balanceOf(user) == amount * 10**18 * DEAD_SHARES // one_token
        assert vault.pricePerShare() == 10**18 // DEAD_SHARES
        vault.redeem(vault.balanceOf(user))
        assert vault.totalAssets() == 0


class StatefulVault(RuleBasedStateMachine):
    user_id = st.integers(min_value=0, max_value=9)
    t = st.integers(min_value=0, max_value=86400 * 365)
    amount = st.integers(min_value=0, max_value=10**9 * 10**18)  # Would never revert - not too huge

    def __init__(self):
        super().__init__()
        for u in self.accounts:
            with boa.env.prank(u):
                self.borrowed_token.approve(self.vault.address, 2**256 - 1)
        assert self.vault.asset() == self.borrowed_token.address
        self.total_assets = 0
        self.precision = 10 ** (18 - self.borrowed_token.decimals())

    @invariant()
    def inv_aprs(self):
        # We are not borrowing anything so just this
        assert self.vault.borrow_apr() == 0
        assert self.vault.lend_apr() == 0

    @invariant()
    def inv_total_assets(self):
        assert self.total_assets == self.vault.totalAssets()

    @rule(user_id=user_id, assets=amount)
    def deposit(self, user_id, assets):
        assets = assets // self.precision
        user = self.accounts[user_id]
        self.borrowed_token._mint_for_testing(user, assets)
        to_mint = self.vault.previewDeposit(assets)
        d_vault_balance = self.vault.balanceOf(user)
        d_user_tokens = self.borrowed_token.balanceOf(user)
        with boa.env.prank(user):
            minted = self.vault.deposit(assets)
        d_vault_balance = self.vault.balanceOf(user) - d_vault_balance
        d_user_tokens -= self.borrowed_token.balanceOf(user)
        assert minted == to_mint
        assert minted == d_vault_balance
        assert d_user_tokens == assets
        self.total_assets += assets

    @rule(user_from=user_id, user_to=user_id, assets=amount)
    def deposit_for(self, user_from, user_to, assets):
        assets = assets // self.precision
        user_from = self.accounts[user_from]
        user_to = self.accounts[user_to]
        self.borrowed_token._mint_for_testing(user_from, assets)
        to_mint = self.vault.previewDeposit(assets)
        d_vault_balance = self.vault.balanceOf(user_to)
        d_user_tokens = self.borrowed_token.balanceOf(user_from)
        with boa.env.prank(user_from):
            minted = self.vault.deposit(assets, user_to)
        d_vault_balance = self.vault.balanceOf(user_to) - d_vault_balance
        d_user_tokens -= self.borrowed_token.balanceOf(user_from)
        assert minted == to_mint
        assert minted == d_vault_balance
        assert d_user_tokens == assets
        self.total_assets += assets

    @rule(user_id=user_id, shares=amount)
    def mint(self, user_id, shares):
        user = self.accounts[user_id]
        assets = self.vault.previewMint(shares)
        self.borrowed_token._mint_for_testing(user, assets)
        d_vault_balance = self.vault.balanceOf(user)
        d_user_tokens = self.borrowed_token.balanceOf(user)
        with boa.env.prank(user):
            assets_deposited = self.vault.mint(shares)
        d_vault_balance = self.vault.balanceOf(user) - d_vault_balance
        d_user_tokens -= self.borrowed_token.balanceOf(user)
        assert assets_deposited == assets
        assert shares == d_vault_balance
        assert d_user_tokens == assets
        self.total_assets += assets

    @rule(user_from=user_id, user_to=user_id, shares=amount)
    def mint_for(self, user_from, user_to, shares):
        user_from = self.accounts[user_from]
        user_to = self.accounts[user_to]
        assets = self.vault.previewMint(shares)
        self.borrowed_token._mint_for_testing(user_from, assets)
        d_vault_balance = self.vault.balanceOf(user_to)
        d_user_tokens = self.borrowed_token.balanceOf(user_from)
        with boa.env.prank(user_from):
            assets_deposited = self.vault.mint(shares, user_to)
        d_vault_balance = self.vault.balanceOf(user_to) - d_vault_balance
        d_user_tokens -= self.borrowed_token.balanceOf(user_from)
        assert assets_deposited == assets
        assert shares == d_vault_balance
        assert d_user_tokens == assets
        self.total_assets += assets


def test_stateful_vault(vault, borrowed_token, accounts, admin, market_amm, market_controller):
    StatefulVault.TestCase.settings = settings(max_examples=500, stateful_step_count=10)
    for k, v in locals().items():
        setattr(StatefulVault, k, v)
    run_state_machine_as_test(StatefulVault)
