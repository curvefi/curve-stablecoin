import boa
from tests.utils import filter_logs, max_approve
from tests.utils.constants import MIN_ASSETS, MIN_TICKS


def test_redeem_basic(
    vault, controller, amm, monetary_policy, borrowed_token, deposit_into_vault
):
    """Test basic redeem functionality - balances, rate, event."""
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(assets=assets)

    initial_sender_balance = vault.balanceOf(boa.env.eoa)
    initial_total_supply = vault.totalSupply()
    initial_balance = controller.available_balance()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_sender_token_balance = borrowed_token.balanceOf(boa.env.eoa)

    initial_amm_rate = amm.rate()
    initial_amm_rate_time = amm.eval("self.rate_time")

    shares_to_redeem = initial_sender_balance // 2

    # Check preview matches
    expected_assets = vault.previewRedeem(shares_to_redeem)

    # Increase rate_time and rate by 1
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Redeem shares
    assets_redeemed = vault.redeem(shares_to_redeem)
    logs = filter_logs(vault, "Withdraw")

    # Check assets match preview
    assert assets_redeemed == expected_assets

    # Check balances
    assert vault.balanceOf(boa.env.eoa) == initial_sender_balance - shares_to_redeem
    assert vault.totalSupply() == initial_total_supply - shares_to_redeem
    assert controller.available_balance() == initial_balance - assets_redeemed
    assert (
        borrowed_token.balanceOf(controller)
        == initial_controller_balance - assets_redeemed
    )
    assert (
        borrowed_token.balanceOf(boa.env.eoa)
        == initial_sender_token_balance + assets_redeemed
    )

    # Check rate was saved
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # Check event was emitted
    assert len(logs) == 1
    assert logs[0].sender == boa.env.eoa
    assert logs[0].receiver == boa.env.eoa
    assert logs[0].owner == boa.env.eoa
    assert logs[0].assets == assets_redeemed
    assert logs[0].shares == shares_to_redeem


def test_redeem_with_receiver(
    vault, controller, amm, monetary_policy, borrowed_token, deposit_into_vault
):
    """Test redeem with receiver argument - assets go to receiver, not sender."""
    # Generate receiver wallet
    receiver = boa.env.generate_address()

    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(assets=assets)

    initial_sender_balance = vault.balanceOf(boa.env.eoa)
    initial_receiver_balance = vault.balanceOf(receiver)
    initial_total_supply = vault.totalSupply()
    initial_balance = controller.available_balance()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_sender_token_balance = borrowed_token.balanceOf(boa.env.eoa)
    initial_receiver_token_balance = borrowed_token.balanceOf(receiver)

    initial_amm_rate = amm.rate()
    initial_amm_rate_time = amm.eval("self.rate_time")

    shares_to_redeem = initial_sender_balance // 2

    # Check preview matches
    expected_assets = vault.previewRedeem(shares_to_redeem)

    # Increase rate_time and rate by 1
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Redeem shares with receiver
    assets_redeemed = vault.redeem(shares_to_redeem, receiver)
    logs = filter_logs(vault, "Withdraw")

    # Check assets match preview
    assert assets_redeemed == expected_assets

    # Check balances - assets go to receiver, not sender
    assert (
        vault.balanceOf(boa.env.eoa) == initial_sender_balance - shares_to_redeem
    )  # Sender shares burned
    assert (
        vault.balanceOf(receiver) == initial_receiver_balance
    )  # Receiver gets no shares
    assert vault.totalSupply() == initial_total_supply - shares_to_redeem
    assert controller.available_balance() == initial_balance - assets_redeemed
    assert (
        borrowed_token.balanceOf(controller)
        == initial_controller_balance - assets_redeemed
    )
    assert (
        borrowed_token.balanceOf(boa.env.eoa) == initial_sender_token_balance
    )  # Sender gets no assets
    assert (
        borrowed_token.balanceOf(receiver)
        == initial_receiver_token_balance + assets_redeemed
    )  # Receiver gets assets

    # Check rate was saved
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # Check event was emitted with correct receiver
    assert len(logs) == 1
    assert logs[0].sender == boa.env.eoa  # Sender is the caller
    assert logs[0].receiver == receiver  # Receiver gets the assets
    assert logs[0].owner == boa.env.eoa  # Owner is the sender
    assert logs[0].assets == assets_redeemed
    assert logs[0].shares == shares_to_redeem


def test_redeem_with_owner(
    vault, controller, amm, monetary_policy, borrowed_token, deposit_into_vault
):
    """Test redeem with owner argument - owner's shares are burned."""
    # Generate owner and caller wallets
    owner = boa.env.generate_address()
    caller = boa.env.generate_address()

    # Deposit for owner
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(user=owner, assets=assets)

    initial_owner_balance = vault.balanceOf(owner)
    initial_caller_balance = vault.balanceOf(caller)
    initial_total_supply = vault.totalSupply()
    initial_balance = controller.available_balance()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_caller_token_balance = borrowed_token.balanceOf(caller)

    initial_amm_rate = amm.rate()
    initial_amm_rate_time = amm.eval("self.rate_time")

    shares_to_redeem = initial_owner_balance // 2

    # Check preview matches
    expected_assets = vault.previewRedeem(shares_to_redeem)

    # Give owner approval to caller
    vault.approve(caller, shares_to_redeem, sender=owner)

    # Increase rate_time and rate by 1
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Redeem shares with owner (caller redeems owner's shares)
    with boa.env.prank(caller):
        assets_redeemed = vault.redeem(shares_to_redeem, caller, owner)
    logs = filter_logs(vault, "Withdraw")

    # Check assets match preview
    assert assets_redeemed == expected_assets

    # Check balances - owner's shares burned, caller gets assets
    assert (
        vault.balanceOf(owner) == initial_owner_balance - shares_to_redeem
    )  # Owner's shares burned
    assert vault.balanceOf(caller) == initial_caller_balance  # Caller gets no shares
    assert vault.totalSupply() == initial_total_supply - shares_to_redeem
    assert controller.available_balance() == initial_balance - assets_redeemed
    assert (
        borrowed_token.balanceOf(controller)
        == initial_controller_balance - assets_redeemed
    )
    assert (
        borrowed_token.balanceOf(caller)
        == initial_caller_token_balance + assets_redeemed
    )  # Caller gets assets

    # Check rate was saved
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # Check event was emitted with correct parameters
    assert len(logs) == 1
    assert logs[0].sender == caller  # Sender is the caller
    assert logs[0].receiver == caller  # Receiver is the caller
    assert logs[0].owner == owner  # Owner is the owner
    assert logs[0].assets == assets_redeemed
    assert logs[0].shares == shares_to_redeem


def test_redeem_with_owner_and_receiver(
    vault, controller, amm, monetary_policy, borrowed_token, deposit_into_vault
):
    """Test redeem with both owner and receiver - owner's shares burned, receiver gets assets."""
    # Generate owner, caller, and receiver wallets
    owner = boa.env.generate_address()
    caller = boa.env.generate_address()
    receiver = boa.env.generate_address()

    # Deposit for owner
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(user=owner, assets=assets)

    initial_owner_balance = vault.balanceOf(owner)
    initial_caller_balance = vault.balanceOf(caller)
    initial_receiver_balance = vault.balanceOf(receiver)
    initial_total_supply = vault.totalSupply()
    initial_balance = controller.available_balance()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_caller_token_balance = borrowed_token.balanceOf(caller)
    initial_receiver_token_balance = borrowed_token.balanceOf(receiver)

    initial_amm_rate = amm.rate()
    initial_amm_rate_time = amm.eval("self.rate_time")

    shares_to_redeem = initial_owner_balance // 2

    # Check preview matches
    expected_assets = vault.previewRedeem(shares_to_redeem)

    # Give owner approval to caller
    vault.approve(caller, shares_to_redeem, sender=owner)

    # Increase rate_time and rate by 1
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Redeem shares with owner and receiver (caller redeems owner's shares to receiver)
    with boa.env.prank(caller):
        assets_redeemed = vault.redeem(shares_to_redeem, receiver, owner)
    logs = filter_logs(vault, "Withdraw")

    # Check assets match preview
    assert assets_redeemed == expected_assets

    # Check balances - owner's shares burned, receiver gets assets
    assert (
        vault.balanceOf(owner) == initial_owner_balance - shares_to_redeem
    )  # Owner's shares burned
    assert vault.balanceOf(caller) == initial_caller_balance  # Caller gets no shares
    assert (
        vault.balanceOf(receiver) == initial_receiver_balance
    )  # Receiver gets no shares
    assert vault.totalSupply() == initial_total_supply - shares_to_redeem
    assert controller.available_balance() == initial_balance - assets_redeemed
    assert (
        borrowed_token.balanceOf(controller)
        == initial_controller_balance - assets_redeemed
    )
    assert (
        borrowed_token.balanceOf(caller) == initial_caller_token_balance
    )  # Caller gets no assets
    assert (
        borrowed_token.balanceOf(receiver)
        == initial_receiver_token_balance + assets_redeemed
    )  # Receiver gets assets

    # Check rate was saved
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # Check event was emitted with correct parameters
    assert len(logs) == 1
    assert logs[0].sender == caller  # Sender is the caller
    assert logs[0].receiver == receiver  # Receiver is the receiver
    assert logs[0].owner == owner  # Owner is the owner
    assert logs[0].assets == assets_redeemed
    assert logs[0].shares == shares_to_redeem


def test_redeem_need_more_assets_revert(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test redeem reverts with 'Need more assets' when total assets too low."""
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(assets=assets)

    # Try to redeem more than available (would leave vault with < MIN_ASSETS)
    total_assets = vault.totalAssets()
    shares_to_redeem = vault.convertToShares(
        total_assets - vault.eval("MIN_ASSETS") + 1
    )

    # Should revert with "Need more assets"
    with boa.reverts("Need more assets"):
        vault.redeem(shares_to_redeem)


def test_revert_full_supply_when_virtual_share_dust_is_below_min_assets(
    vault, controller, monetary_policy, collateral_token, admin
):
    full_balance = vault.balanceOf(admin)
    assert full_balance == vault.totalSupply()

    borrower = boa.env.generate_address("borrower")
    collateral_amount = 10_000 * 10 ** collateral_token.decimals()
    boa.deal(collateral_token, borrower, collateral_amount)

    with boa.env.prank(borrower):
        max_approve(collateral_token, controller.address)
        debt = controller.max_borrowable(collateral_amount, MIN_TICKS)
        controller.create_loan(collateral_amount, debt, MIN_TICKS)

    initial_total_assets = vault.totalAssets()
    annual_rate = 10**18 // (365 * 86400)

    with boa.env.prank(admin):
        monetary_policy.set_rate(annual_rate)

    boa.env.time_travel(365 * 86400)
    controller.save_rate()

    assert vault.totalAssets() > initial_total_assets

    assets_to_redeem = vault.previewRedeem(full_balance)
    dust = vault.totalAssets() - assets_to_redeem

    assert assets_to_redeem < vault.totalAssets()
    assert 0 < dust < MIN_ASSETS

    with boa.env.prank(admin):
        with boa.reverts("Need more assets"):
            vault.redeem(full_balance)


def test_default_behavior_full_supply_when_conversion_equals_total_assets(
    vault, controller, borrowed_token, admin
):
    full_balance = vault.balanceOf(admin)
    assert full_balance == vault.totalSupply()

    preview_assets = vault.previewRedeem(full_balance)
    total_assets = vault.totalAssets()
    initial_admin_token_balance = borrowed_token.balanceOf(admin)

    assert preview_assets == total_assets

    with boa.env.prank(admin):
        assets_redeemed = vault.redeem(full_balance, admin, admin)
    logs = filter_logs(vault, "Withdraw")

    assert assets_redeemed == total_assets
    assert (
        borrowed_token.balanceOf(admin) == initial_admin_token_balance + assets_redeemed
    )
    assert vault.totalSupply() == 0
    assert vault.totalAssets() == 0

    assert len(logs) == 1
    assert logs[0].sender == admin
    assert logs[0].receiver == admin
    assert logs[0].owner == admin
    assert logs[0].assets == assets_redeemed
    assert logs[0].shares == full_balance


def test_redeem_insufficient_allowance_revert(
    vault, controller, amm, monetary_policy, borrowed_token, deposit_into_vault
):
    """Test redeem reverts when allowance < shares."""
    # Generate owner and caller wallets
    owner = boa.env.generate_address()
    caller = boa.env.generate_address()

    # Deposit for owner
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(user=owner, assets=assets)

    # Give owner some allowance to caller, but less than needed
    shares_to_redeem = vault.balanceOf(owner) // 2
    insufficient_allowance = shares_to_redeem - 1  # Less than needed
    vault.approve(caller, insufficient_allowance, sender=owner)

    # Try to redeem with insufficient allowance
    with boa.env.prank(caller):
        with boa.reverts():
            vault.redeem(shares_to_redeem, caller, owner)
