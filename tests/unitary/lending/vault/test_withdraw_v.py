import boa
from tests.utils import filter_logs


def test_withdraw_basic(
    vault, controller, amm, monetary_policy, borrowed_token, deposit_into_vault
):
    """Test basic withdraw functionality - balances, rate, event."""
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(assets=assets)

    initial_sender_balance = vault.balanceOf(boa.env.eoa)
    initial_total_supply = vault.totalSupply()
    initial_withdrawn = vault.withdrawn()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_sender_token_balance = borrowed_token.balanceOf(boa.env.eoa)

    initial_amm_rate = amm.rate()
    initial_amm_rate_time = amm.eval("self.rate_time")

    assets_to_withdraw = assets // 2

    # Check preview matches
    expected_shares = vault.previewWithdraw(assets_to_withdraw)

    # Increase rate_time and rate by 1
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Withdraw assets
    shares = vault.withdraw(assets_to_withdraw)
    logs = filter_logs(vault, "Withdraw")

    # Check shares match preview
    assert shares == expected_shares

    # Check balances
    assert vault.balanceOf(boa.env.eoa) == initial_sender_balance - shares
    assert vault.totalSupply() == initial_total_supply - shares
    assert vault.withdrawn() == initial_withdrawn + assets_to_withdraw
    assert (
        borrowed_token.balanceOf(controller)
        == initial_controller_balance - assets_to_withdraw
    )
    assert (
        borrowed_token.balanceOf(boa.env.eoa)
        == initial_sender_token_balance + assets_to_withdraw
    )

    # Check rate was saved
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # Check event was emitted
    assert len(logs) == 1
    assert logs[0].sender == boa.env.eoa
    assert logs[0].receiver == boa.env.eoa
    assert logs[0].owner == boa.env.eoa
    assert logs[0].assets == assets_to_withdraw
    assert logs[0].shares == shares


def test_withdraw_with_receiver(
    vault, controller, amm, monetary_policy, borrowed_token, deposit_into_vault
):
    """Test withdraw with receiver argument - assets go to receiver, not sender."""
    # Generate receiver wallet
    receiver = boa.env.generate_address()

    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(assets=assets)

    initial_sender_balance = vault.balanceOf(boa.env.eoa)
    initial_receiver_balance = vault.balanceOf(receiver)
    initial_total_supply = vault.totalSupply()
    initial_withdrawn = vault.withdrawn()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_sender_token_balance = borrowed_token.balanceOf(boa.env.eoa)
    initial_receiver_token_balance = borrowed_token.balanceOf(receiver)

    initial_amm_rate = amm.rate()
    initial_amm_rate_time = amm.eval("self.rate_time")

    assets_to_withdraw = assets // 2

    # Check preview matches
    expected_shares = vault.previewWithdraw(assets_to_withdraw)

    # Increase rate_time and rate by 1
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Withdraw assets with receiver
    shares = vault.withdraw(assets_to_withdraw, receiver)
    logs = filter_logs(vault, "Withdraw")

    # Check shares match preview
    assert shares == expected_shares

    # Check balances - assets go to receiver, not sender
    assert (
        vault.balanceOf(boa.env.eoa) == initial_sender_balance - shares
    )  # Sender shares burned
    assert (
        vault.balanceOf(receiver) == initial_receiver_balance
    )  # Receiver gets no shares
    assert vault.totalSupply() == initial_total_supply - shares
    assert vault.withdrawn() == initial_withdrawn + assets_to_withdraw
    assert (
        borrowed_token.balanceOf(controller)
        == initial_controller_balance - assets_to_withdraw
    )
    assert (
        borrowed_token.balanceOf(boa.env.eoa) == initial_sender_token_balance
    )  # Sender gets no assets
    assert (
        borrowed_token.balanceOf(receiver)
        == initial_receiver_token_balance + assets_to_withdraw
    )  # Receiver gets assets

    # Check rate was saved
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # Check event was emitted with correct receiver
    assert len(logs) == 1
    assert logs[0].sender == boa.env.eoa  # Sender is the caller
    assert logs[0].receiver == receiver  # Receiver gets the assets
    assert logs[0].owner == boa.env.eoa  # Owner is the sender
    assert logs[0].assets == assets_to_withdraw
    assert logs[0].shares == shares


def test_withdraw_with_owner(
    vault, controller, amm, monetary_policy, borrowed_token, deposit_into_vault
):
    """Test withdraw with owner argument - owner's shares are burned."""
    # Generate owner and caller wallets
    owner = boa.env.generate_address()
    caller = boa.env.generate_address()

    # Deposit for owner
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(user=owner, assets=assets)

    initial_owner_balance = vault.balanceOf(owner)
    initial_caller_balance = vault.balanceOf(caller)
    initial_total_supply = vault.totalSupply()
    initial_withdrawn = vault.withdrawn()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_caller_token_balance = borrowed_token.balanceOf(caller)

    initial_amm_rate = amm.rate()
    initial_amm_rate_time = amm.eval("self.rate_time")

    assets_to_withdraw = assets // 2

    # Check preview matches
    expected_shares = vault.previewWithdraw(assets_to_withdraw)

    # Give owner approval to caller
    vault.approve(caller, expected_shares, sender=owner)

    # Increase rate_time and rate by 1
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Withdraw assets with owner (caller withdraws owner's shares)
    with boa.env.prank(caller):
        shares = vault.withdraw(assets_to_withdraw, caller, owner)
    logs = filter_logs(vault, "Withdraw")

    # Check shares match preview
    assert shares == expected_shares

    # Check balances - owner's shares burned, caller gets assets
    assert (
        vault.balanceOf(owner) == initial_owner_balance - shares
    )  # Owner's shares burned
    assert vault.balanceOf(caller) == initial_caller_balance  # Caller gets no shares
    assert vault.totalSupply() == initial_total_supply - shares
    assert vault.withdrawn() == initial_withdrawn + assets_to_withdraw
    assert (
        borrowed_token.balanceOf(controller)
        == initial_controller_balance - assets_to_withdraw
    )
    assert (
        borrowed_token.balanceOf(caller)
        == initial_caller_token_balance + assets_to_withdraw
    )  # Caller gets assets

    # Check rate was saved
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # Check event was emitted with correct parameters
    assert len(logs) == 1
    assert logs[0].sender == caller  # Sender is the caller
    assert logs[0].receiver == caller  # Receiver is the caller
    assert logs[0].owner == owner  # Owner is the owner
    assert logs[0].assets == assets_to_withdraw
    assert logs[0].shares == shares


def test_withdraw_with_owner_and_receiver(
    vault, controller, amm, monetary_policy, borrowed_token, deposit_into_vault
):
    """Test withdraw with both owner and receiver - owner's shares burned, receiver gets assets."""
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
    initial_withdrawn = vault.withdrawn()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_owner_token_balance = borrowed_token.balanceOf(owner)
    initial_caller_token_balance = borrowed_token.balanceOf(caller)
    initial_receiver_token_balance = borrowed_token.balanceOf(receiver)

    initial_amm_rate = amm.rate()
    initial_amm_rate_time = amm.eval("self.rate_time")

    assets_to_withdraw = assets // 2

    # Check preview matches
    expected_shares = vault.previewWithdraw(assets_to_withdraw)

    # Give owner approval to caller
    vault.approve(caller, expected_shares, sender=owner)

    # Increase rate_time and rate by 1
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Withdraw assets with owner and receiver (caller withdraws owner's shares to receiver)
    with boa.env.prank(caller):
        shares = vault.withdraw(assets_to_withdraw, receiver, owner)
    logs = filter_logs(vault, "Withdraw")

    # Check shares match preview
    assert shares == expected_shares

    # Check balances - owner's shares burned, receiver gets assets
    assert (
        vault.balanceOf(owner) == initial_owner_balance - shares
    )  # Owner's shares burned
    assert vault.balanceOf(caller) == initial_caller_balance  # Caller gets no shares
    assert (
        vault.balanceOf(receiver) == initial_receiver_balance
    )  # Receiver gets no shares
    assert vault.totalSupply() == initial_total_supply - shares
    assert vault.withdrawn() == initial_withdrawn + assets_to_withdraw
    assert (
        borrowed_token.balanceOf(controller)
        == initial_controller_balance - assets_to_withdraw
    )
    assert (
        borrowed_token.balanceOf(owner) == initial_owner_token_balance
    )  # Owner gets no assets
    assert (
        borrowed_token.balanceOf(caller) == initial_caller_token_balance
    )  # Caller gets no assets
    assert (
        borrowed_token.balanceOf(receiver)
        == initial_receiver_token_balance + assets_to_withdraw
    )  # Receiver gets assets

    # Check rate was saved
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # Check event was emitted with correct parameters
    assert len(logs) == 1
    assert logs[0].sender == caller  # Sender is the caller
    assert logs[0].receiver == receiver  # Receiver is the receiver
    assert logs[0].owner == owner  # Owner is the owner
    assert logs[0].assets == assets_to_withdraw
    assert logs[0].shares == shares


def test_withdraw_need_more_assets_revert(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test withdraw reverts with 'Need more assets' when total assets too low."""
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(assets=assets)

    # Try to withdraw more than available (would leave vault with < MIN_ASSETS)
    total_assets = vault.totalAssets()
    withdraw_amount = (
        total_assets - vault.eval("MIN_ASSETS") + 1
    )  # Would leave < MIN_ASSETS

    # Should revert with "Need more assets"
    with boa.reverts("Need more assets"):
        vault.withdraw(withdraw_amount)


def test_withdraw_insufficient_allowance_revert(
    vault, controller, amm, monetary_policy, borrowed_token, deposit_into_vault
):
    """Test withdraw reverts when allowance < shares."""
    # Generate owner and caller wallets
    owner = boa.env.generate_address()
    caller = boa.env.generate_address()

    # Deposit for owner
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(user=owner, assets=assets)

    # Give owner some allowance to caller, but less than needed
    expected_shares = vault.previewWithdraw(assets)
    insufficient_allowance = expected_shares - 1  # Less than needed
    vault.approve(caller, insufficient_allowance, sender=owner)

    # Try to withdraw with insufficient allowance
    with boa.env.prank(caller):
        with boa.reverts():
            vault.withdraw(assets, caller, owner)
