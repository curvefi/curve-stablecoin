import boa
import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    run_state_machine_as_test,
    rule,
    invariant,
)

from tests.utils.constants import DEAD_SHARES

SECONDS_PER_YEAR = 365 * 86400


@pytest.fixture(scope="module")
def min_borrow_rate():
    """Keep borrow APR aligned with stateful invariant (0.5% APR)."""
    return (5 * 10**15) // SECONDS_PER_YEAR


@pytest.fixture(scope="module")
def max_borrow_rate():
    return (50 * 10**16) // SECONDS_PER_YEAR


@pytest.fixture(scope="module")
def seed_liquidity():
    """Override to 0"""
    return 0


def test_vault_creation(
    vault,
    controller,
    amm,
    monetary_policy,
    factory,
    price_oracle,
    borrowed_token,
    collateral_token,
    stablecoin,
):
    assert vault.amm() == amm.address
    assert vault.controller() == controller.address
    assert controller.monetary_policy() == monetary_policy.address
    n = factory.market_count()
    assert n > 0
    assert factory.vaults(n - 1) == vault.address
    assert factory.amms(n - 1) == amm.address
    assert factory.controllers(n - 1) == controller.address
    assert factory.borrowed_tokens(n - 1) == borrowed_token.address
    assert factory.collateral_tokens(n - 1) == collateral_token.address
    assert factory.price_oracles(n - 1) == price_oracle.address
    assert factory.monetary_policies(n - 1) == monetary_policy.address

    assert factory.vaults(factory.vaults_index(vault.address)) == vault.address


@pytest.mark.parametrize("supply_limit", [0, 1000 * 10**18, 2**256 - 1, None])
def test_deposit_and_withdraw(vault, borrowed_token, accounts, admin, supply_limit):
    one_token = 10 ** borrowed_token.decimals()
    amount = 10**6 * one_token
    user = accounts[1]
    boa.deal(borrowed_token, user, amount)

    if supply_limit is not None:
        with boa.env.prank(admin):
            vault.set_max_supply(supply_limit)
    else:
        supply_limit = 2**256 - 1

    with boa.env.prank(user):
        assert vault.pricePerShare() == 10**18 // DEAD_SHARES
        borrowed_token.approve(vault.address, 2**256 - 1)
        if amount > supply_limit:
            with boa.reverts():
                vault.deposit(amount)
        else:
            vault.deposit(amount)
            assert vault.totalAssets() == amount
            assert vault.balanceOf(user) == amount * 10**18 * DEAD_SHARES // one_token
            assert (
                vault.pricePerShare() == 10**18 // DEAD_SHARES
            )  # We test different precisions here, and pps is the same
            vault.redeem(vault.balanceOf(user))
            assert vault.totalAssets() == 0


class StatefulVault(RuleBasedStateMachine):
    user_id = st.integers(min_value=0, max_value=9)
    t = st.integers(min_value=0, max_value=86400 * 365)
    amount = st.integers(
        min_value=0, max_value=10**9 * 10**18
    )  # Would never revert - not too huge

    def __init__(self):
        super().__init__()
        for u in self.accounts:
            with boa.env.prank(u):
                self.borrowed_token.approve(self.vault.address, 2**256 - 1)
        assert self.vault.asset() == self.borrowed_token.address
        self.total_assets = 0
        self.precision = 10 ** (18 - self.borrowed_token.decimals())
        self.pps = None
        self.was_used = False

    @invariant()
    def inv_aprs(self):
        if self.was_used:
            assert self.vault.borrow_apr() / 1e18 == pytest.approx(0.005, rel=1e-5)
        else:
            assert self.vault.borrow_apr() == 0
        assert self.vault.lend_apr() == 0

    @invariant()
    def inv_total_assets(self):
        assert self.total_assets == self.vault.totalAssets()

    @invariant()
    def inv_pps(self):
        pps = self.vault.pricePerShare()
        assert pps >= 1e18 // 1000  # Most likely we'll be around here
        assert (
            pps <= 1e18 // 1000 * 1.1
        )  # Cannot pump much due to min assets limits (this test only pupms via rounding errors)
        if self.total_assets > 100000:
            if self.pps:
                assert pps == pytest.approx(self.pps, rel=1e-2)
            else:
                self.pps = pps

    @rule(user_id=user_id, assets=amount)
    def deposit(self, user_id, assets):
        assets = assets // self.precision
        user = self.accounts[user_id]
        boa.deal(self.borrowed_token, user, assets)
        to_mint = self.vault.previewDeposit(assets)
        d_vault_balance = self.vault.balanceOf(user)
        d_user_tokens = self.borrowed_token.balanceOf(user)
        with boa.env.prank(user):
            if self.total_assets + assets < 10000:
                with boa.reverts():
                    self.vault.deposit(assets)
                return
            else:
                minted = self.vault.deposit(assets)
        self.was_used = True
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
        boa.deal(self.borrowed_token, user_from, assets)
        to_mint = self.vault.previewDeposit(assets)
        d_vault_balance = self.vault.balanceOf(user_to)
        d_user_tokens = self.borrowed_token.balanceOf(user_from)
        with boa.env.prank(user_from):
            if self.total_assets + assets < 10000:
                with boa.reverts():
                    self.vault.deposit(assets, user_to)
                return
            else:
                minted = self.vault.deposit(assets, user_to)
        self.was_used = True
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
        boa.deal(self.borrowed_token, user, assets)
        d_vault_balance = self.vault.balanceOf(user)
        d_user_tokens = self.borrowed_token.balanceOf(user)
        with boa.env.prank(user):
            if self.total_assets + assets < 10000:
                with boa.reverts():
                    self.vault.mint(shares)
                return
            else:
                assets_deposited = self.vault.mint(shares)
        self.was_used = True
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
        boa.deal(self.borrowed_token, user_from, assets)
        d_vault_balance = self.vault.balanceOf(user_to)
        d_user_tokens = self.borrowed_token.balanceOf(user_from)
        with boa.env.prank(user_from):
            if self.total_assets + assets < 10000:
                with boa.reverts():
                    self.vault.mint(shares, user_to)
                return
            else:
                assets_deposited = self.vault.mint(shares, user_to)
        self.was_used = True
        d_vault_balance = self.vault.balanceOf(user_to) - d_vault_balance
        d_user_tokens -= self.borrowed_token.balanceOf(user_from)
        assert assets_deposited == assets
        assert shares == d_vault_balance
        assert d_user_tokens == assets
        self.total_assets += assets

    @rule(user_id=user_id, shares=amount)
    def redeem(self, user_id, shares):
        user = self.accounts[user_id]
        max_redeem = self.vault.maxRedeem(user)
        if shares <= max_redeem:
            assets = self.vault.previewRedeem(shares)
            d_vault_balance = self.vault.balanceOf(user)
            d_user_tokens = self.borrowed_token.balanceOf(user)
            with boa.env.prank(user):
                if (
                    self.total_assets - assets < 10000
                    and self.total_assets - assets != 0
                ):
                    with boa.reverts():
                        self.vault.redeem(shares)
                    return
                else:
                    assets_redeemed = self.vault.redeem(shares)
            self.was_used = True
            d_vault_balance -= self.vault.balanceOf(user)
            d_user_tokens = self.borrowed_token.balanceOf(user) - d_user_tokens
            assert assets_redeemed == assets
            assert shares == d_vault_balance
            assert d_user_tokens == assets
            self.total_assets -= assets

        else:
            with boa.reverts():
                with boa.env.prank(user):
                    self.vault.redeem(shares)

    @rule(user_from=user_id, user_to=user_id, shares=amount)
    def redeem_for(self, user_from, user_to, shares):
        user_from = self.accounts[user_from]
        user_to = self.accounts[user_to]
        max_redeem = self.vault.maxRedeem(user_from)
        if shares <= max_redeem:
            assets = self.vault.previewRedeem(shares)
            d_vault_balance = self.vault.balanceOf(user_from)
            d_user_tokens = self.borrowed_token.balanceOf(user_to)
            with boa.env.prank(user_from):
                if (
                    self.total_assets - assets < 10000
                    and self.total_assets - assets != 0
                ):
                    with boa.reverts():
                        self.vault.redeem(shares, user_to)
                    return
                else:
                    assets_redeemed = self.vault.redeem(shares, user_to)
            self.was_used = True
            d_vault_balance -= self.vault.balanceOf(user_from)
            d_user_tokens = self.borrowed_token.balanceOf(user_to) - d_user_tokens
            assert assets_redeemed == assets
            assert shares == d_vault_balance
            assert d_user_tokens == assets
            self.total_assets -= assets

        else:
            with boa.reverts():
                with boa.env.prank(user_from):
                    self.vault.redeem(shares, user_to)

    @rule(
        user_from=user_id,
        user_to=user_id,
        owner=user_id,
        shares=amount,
        approval=amount,
    )
    def redeem_owner_for(self, user_from, user_to, owner, shares, approval):
        if user_from == owner:
            return
        user_from = self.accounts[user_from]
        user_to = self.accounts[user_to]
        owner = self.accounts[owner]
        max_redeem = self.vault.maxRedeem(owner)
        if shares <= max_redeem:
            with boa.env.prank(owner):
                self.vault.approve(user_from, approval)
            if approval >= shares:
                assets = self.vault.previewRedeem(shares)
                d_vault_balance = self.vault.balanceOf(owner)
                d_user_tokens = self.borrowed_token.balanceOf(user_to)
                with boa.env.prank(user_from):
                    if (
                        self.total_assets - assets < 10000
                        and self.total_assets - assets != 0
                    ):
                        with boa.reverts():
                            self.vault.redeem(shares, user_to, owner)
                        return
                    else:
                        assets_redeemed = self.vault.redeem(shares, user_to, owner)
                self.was_used = True
                d_vault_balance -= self.vault.balanceOf(owner)
                d_user_tokens = self.borrowed_token.balanceOf(user_to) - d_user_tokens
                assert assets_redeemed == assets
                assert shares == d_vault_balance
                assert d_user_tokens == assets
                self.total_assets -= assets
            else:
                with boa.reverts():
                    with boa.env.prank(user_from):
                        self.vault.redeem(shares, user_to, owner)
            with boa.env.prank(owner):
                self.vault.approve(user_from, 0)

        else:
            with boa.env.prank(owner):
                self.vault.approve(user_from, 2**256 - 1)
            with boa.reverts():
                with boa.env.prank(user_from):
                    self.vault.redeem(shares, user_to, owner)
            with boa.env.prank(owner):
                self.vault.approve(user_from, 0)

    @rule(user_id=user_id, assets=amount)
    def withdraw(self, user_id, assets):
        user = self.accounts[user_id]
        max_withdraw = self.vault.maxWithdraw(user)
        if assets <= max_withdraw:
            shares = self.vault.previewWithdraw(assets)
            d_vault_balance = self.vault.balanceOf(user)
            d_user_tokens = self.borrowed_token.balanceOf(user)
            with boa.env.prank(user):
                if (
                    self.total_assets - assets < 10000
                    and self.total_assets - assets != 0
                ):
                    with boa.reverts():
                        self.vault.withdraw(assets)
                    return
                else:
                    shares_withdrawn = self.vault.withdraw(assets)
            self.was_used = True
            d_vault_balance -= self.vault.balanceOf(user)
            d_user_tokens = self.borrowed_token.balanceOf(user) - d_user_tokens
            assert shares_withdrawn == shares
            assert shares == d_vault_balance
            assert d_user_tokens == assets
            self.total_assets -= assets

        else:
            with boa.reverts():
                with boa.env.prank(user):
                    self.vault.withdraw(assets)

    @rule(user_from=user_id, user_to=user_id, assets=amount)
    def withdraw_for(self, user_from, user_to, assets):
        user_from = self.accounts[user_from]
        user_to = self.accounts[user_to]
        max_withdraw = self.vault.maxWithdraw(user_from)
        if assets <= max_withdraw:
            shares = self.vault.previewWithdraw(assets)
            d_vault_balance = self.vault.balanceOf(user_from)
            d_user_tokens = self.borrowed_token.balanceOf(user_to)
            with boa.env.prank(user_from):
                if (
                    self.total_assets - assets < 10000
                    and self.total_assets - assets != 0
                ):
                    with boa.reverts():
                        self.vault.withdraw(assets, user_to)
                    return
                else:
                    shares_withdrawn = self.vault.withdraw(assets, user_to)
            self.was_used = True
            d_vault_balance -= self.vault.balanceOf(user_from)
            d_user_tokens = self.borrowed_token.balanceOf(user_to) - d_user_tokens
            assert shares_withdrawn == shares
            assert shares == d_vault_balance
            assert d_user_tokens == assets
            self.total_assets -= assets

        else:
            with boa.reverts():
                with boa.env.prank(user_from):
                    self.vault.withdraw(assets, user_to)

    @rule(
        user_from=user_id,
        user_to=user_id,
        owner=user_id,
        assets=amount,
        approval=amount,
    )
    def withdraw_owner_for(self, user_from, user_to, owner, assets, approval):
        if user_from == owner:
            return
        user_from = self.accounts[user_from]
        user_to = self.accounts[user_to]
        owner = self.accounts[owner]
        max_withdraw = self.vault.maxWithdraw(owner)
        if assets <= max_withdraw:
            with boa.env.prank(owner):
                self.vault.approve(user_from, approval)
            shares = self.vault.previewWithdraw(assets)
            if approval >= shares:
                d_vault_balance = self.vault.balanceOf(owner)
                d_user_tokens = self.borrowed_token.balanceOf(user_to)
                with boa.env.prank(user_from):
                    if (
                        self.total_assets - assets < 10000
                        and self.total_assets - assets != 0
                    ):
                        with boa.reverts():
                            self.vault.withdraw(assets, user_to, owner)
                        return
                    else:
                        shares_withdrawn = self.vault.withdraw(assets, user_to, owner)
                self.was_used = True
                d_vault_balance -= self.vault.balanceOf(owner)
                d_user_tokens = self.borrowed_token.balanceOf(user_to) - d_user_tokens
                assert shares_withdrawn == shares
                assert shares == d_vault_balance
                assert d_user_tokens == assets
                self.total_assets -= assets
            else:
                with boa.reverts():
                    with boa.env.prank(user_from):
                        self.vault.withdraw(assets, user_to, owner)
            with boa.env.prank(owner):
                self.vault.approve(user_from, 0)

        else:
            with boa.env.prank(owner):
                self.vault.approve(user_from, 2**256 - 1)
            with boa.reverts():
                with boa.env.prank(user_from):
                    self.vault.withdraw(assets, user_to, owner)
            with boa.env.prank(owner):
                self.vault.approve(user_from, 0)


def test_stateful_vault(vault, borrowed_token, accounts, admin, amm, controller):
    StatefulVault.TestCase.settings = settings(max_examples=500, stateful_step_count=50)
    for k, v in locals().items():
        setattr(StatefulVault, k, v)
    run_state_machine_as_test(StatefulVault)
