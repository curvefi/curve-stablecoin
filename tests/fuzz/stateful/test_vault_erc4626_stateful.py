import boa
from hypothesis import assume, event, note
from hypothesis.stateful import precondition, rule
from hypothesis.strategies import data, integers, sampled_from

from tests.fuzz.stateful.stateful_base import LlamalendStatefulBase


class VaultERC4626Stateful(LlamalendStatefulBase):
    """
    Focused ERC4626 coverage for the lending vault.

    This intentionally keeps controller borrowing out of the rules and exercises
    the vault API surface that the controller-level state machine only touches
    through deposit/withdraw.
    """

    def bounded_asset_amount(self, data, user: str, label: str):
        max_deposit = int(self.vault.maxDeposit(user))
        assume(max_deposit > 0)

        token_decimals = int(self.vault_borrowed_token.decimals())
        upper_bound = min(max_deposit, 10**6 * 10**token_decimals)
        assume(upper_bound > 0)
        return data.draw(integers(min_value=1, max_value=upper_bound), label=label)

    def bounded_share_amount(self, data, user: str, label: str):
        token_decimals = int(self.vault_borrowed_token.decimals())
        max_assets = min(int(self.vault.maxDeposit(user)), 10**6 * 10**token_decimals)
        assume(max_assets > 0)

        max_shares = min(int(self.vault.maxMint(user)), int(self.vault.previewDeposit(max_assets)))
        assume(max_shares > 0)
        return data.draw(integers(min_value=1, max_value=max_shares), label=label)

    @rule(data=data())
    def deposit_for(self, data):
        note("[VAULT DEPOSIT FOR]")
        sender = boa.env.generate_address(f"vault_sender_{len(self.vault_users)}")
        receiver = boa.env.generate_address(f"vault_receiver_{len(self.vault_users)}")
        assets = self.bounded_asset_amount(data, receiver, "vault_deposit_assets")

        expected_shares = self.vault.previewDeposit(assets)
        sender_before = self.vault_borrowed_token.balanceOf(sender)
        receiver_shares_before = self.vault.balanceOf(receiver)
        total_assets_before = self.vault.totalAssets()

        boa.deal(self.vault_borrowed_token, sender, assets)
        with boa.env.prank(sender):
            self.vault_borrowed_token.approve(self.vault.address, 2**256 - 1)
            minted = self.vault.deposit(assets, receiver)

        assert minted == expected_shares
        assert self.vault.balanceOf(receiver) - receiver_shares_before == minted
        assert sender_before + assets - self.vault_borrowed_token.balanceOf(sender) == assets
        assert self.vault.totalAssets() >= total_assets_before + assets
        self.vault_users.append(receiver)
        event("stateful:vault:deposit_for")

    @rule(data=data())
    def mint_for(self, data):
        note("[VAULT MINT FOR]")
        sender = boa.env.generate_address(f"vault_minter_{len(self.vault_users)}")
        receiver = boa.env.generate_address(f"vault_mint_receiver_{len(self.vault_users)}")
        shares = self.bounded_share_amount(data, receiver, "vault_mint_shares")

        expected_assets = self.vault.previewMint(shares)
        receiver_shares_before = self.vault.balanceOf(receiver)
        total_assets_before = self.vault.totalAssets()

        boa.deal(self.vault_borrowed_token, sender, expected_assets)
        with boa.env.prank(sender):
            self.vault_borrowed_token.approve(self.vault.address, 2**256 - 1)
            assets = self.vault.mint(shares, receiver)

        assert assets == expected_assets
        assert self.vault.balanceOf(receiver) - receiver_shares_before == shares
        assert self.vault.totalAssets() >= total_assets_before + assets
        self.vault_users.append(receiver)
        event("stateful:vault:mint_for")

    @precondition(lambda self: len(self.vault_users) > 0)
    @rule(data=data())
    def withdraw(self, data):
        note("[VAULT WITHDRAW]")
        user = data.draw(sampled_from(self.vault_users), label="vault_withdraw_user")
        max_withdraw = int(self.vault.maxWithdraw(user))
        assume(max_withdraw > 0)

        assets = data.draw(
            integers(min_value=1, max_value=max_withdraw),
            label="vault_withdraw_assets",
        )
        expected_shares = self.vault.previewWithdraw(assets)
        shares_before = self.vault.balanceOf(user)
        assets_before = self.vault_borrowed_token.balanceOf(user)

        with boa.env.prank(user):
            burned = self.vault.withdraw(assets, user)

        assert burned == expected_shares
        assert shares_before - self.vault.balanceOf(user) == burned
        assert self.vault_borrowed_token.balanceOf(user) - assets_before == assets
        if self.vault.balanceOf(user) == 0:
            self.vault_users.remove(user)
        event("stateful:vault:withdraw")

    @precondition(lambda self: len(self.vault_users) > 0)
    @rule(data=data())
    def redeem(self, data):
        note("[VAULT REDEEM]")
        user = data.draw(sampled_from(self.vault_users), label="vault_redeem_user")
        max_redeem = int(self.vault.maxRedeem(user))
        assume(max_redeem > 0)

        shares = data.draw(
            integers(min_value=1, max_value=max_redeem),
            label="vault_redeem_shares",
        )
        expected_assets = self.vault.previewRedeem(shares)
        shares_before = self.vault.balanceOf(user)
        assets_before = self.vault_borrowed_token.balanceOf(user)

        with boa.env.prank(user):
            assets = self.vault.redeem(shares, user)

        assert assets == expected_assets
        assert shares_before - self.vault.balanceOf(user) == shares
        assert self.vault_borrowed_token.balanceOf(user) - assets_before == assets
        if self.vault.balanceOf(user) == 0:
            self.vault_users.remove(user)
        event("stateful:vault:redeem")

    @precondition(lambda self: len(self.vault_users) > 0)
    @rule(data=data())
    def withdraw_owner_for(self, data):
        note("[VAULT WITHDRAW OWNER FOR]")
        owner = data.draw(sampled_from(self.vault_users), label="vault_owner")
        max_withdraw = int(self.vault.maxWithdraw(owner))
        assume(max_withdraw > 0)

        spender = boa.env.generate_address("vault_withdraw_spender")
        receiver = boa.env.generate_address("vault_withdraw_receiver")
        assets = data.draw(
            integers(min_value=1, max_value=max_withdraw),
            label="vault_owner_withdraw_assets",
        )
        expected_shares = self.vault.previewWithdraw(assets)

        with boa.env.prank(owner):
            self.vault.approve(spender, expected_shares)
        with boa.env.prank(spender):
            burned = self.vault.withdraw(assets, receiver, owner)

        assert burned == expected_shares
        if self.vault.balanceOf(owner) == 0:
            self.vault_users.remove(owner)
        event("stateful:vault:withdraw_owner_for")

    @precondition(lambda self: len(self.vault_users) > 0)
    @rule(data=data())
    def redeem_owner_for(self, data):
        note("[VAULT REDEEM OWNER FOR]")
        owner = data.draw(sampled_from(self.vault_users), label="vault_redeem_owner")
        max_redeem = int(self.vault.maxRedeem(owner))
        assume(max_redeem > 0)

        spender = boa.env.generate_address("vault_redeem_spender")
        receiver = boa.env.generate_address("vault_redeem_receiver")
        shares = data.draw(
            integers(min_value=1, max_value=max_redeem),
            label="vault_owner_redeem_shares",
        )
        expected_assets = self.vault.previewRedeem(shares)

        with boa.env.prank(owner):
            self.vault.approve(spender, shares)
        with boa.env.prank(spender):
            assets = self.vault.redeem(shares, receiver, owner)

        assert assets == expected_assets
        if self.vault.balanceOf(owner) == 0:
            self.vault_users.remove(owner)
        event("stateful:vault:redeem_owner_for")


TestVaultERC4626 = VaultERC4626Stateful.TestCase
