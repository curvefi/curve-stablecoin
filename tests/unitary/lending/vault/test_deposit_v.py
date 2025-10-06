import boa
import pytest
from tests.utils import filter_logs


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 0


def test_deposit_basic(vault, controller, amm, monetary_policy, borrowed_token):
    """Test basic deposit functionality - balances, rate, event."""
    initial_sender_balance = vault.balanceOf(boa.env.eoa)
    initial_deposited = vault.deposited()
    initial_total_supply = vault.totalSupply()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_amm_rate = amm.rate()

    assert amm.eval("self.rate_time") == 0

    assets = 100 * 10 ** borrowed_token.decimals()

    # Give user tokens and approve vault
    boa.deal(borrowed_token, boa.env.eoa, assets)
    borrowed_token.approve(vault, assets)

    # Check preview matches
    expected_shares = vault.previewDeposit(assets)

    # Increase rate by 1
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Deposit assets
    shares = vault.deposit(assets)
    logs = filter_logs(vault, "Deposit")

    # Check shares match preview
    assert shares == expected_shares

    # Check balances
    assert vault.balanceOf(boa.env.eoa) == initial_sender_balance + shares
    assert vault.deposited() == initial_deposited + assets
    assert vault.totalSupply() == initial_total_supply + shares
    assert (
        borrowed_token.balanceOf(controller.address)
        == initial_controller_balance + assets
    )
    assert borrowed_token.balanceOf(boa.env.eoa) == 0

    # Check rate was saved
    assert amm.eval("self.rate_time") > 0
    assert amm.rate() == initial_amm_rate + 1

    # Check event was emitted
    assert len(logs) == 1
    assert logs[0].sender == boa.env.eoa
    assert logs[0].owner == boa.env.eoa
    assert logs[0].assets == assets
    assert logs[0].shares == shares


def test_deposit_with_receiver(vault, controller, amm, monetary_policy, borrowed_token):
    """Test deposit with receiver argument - shares go to receiver, not sender."""
    # Generate receiver wallet
    receiver = boa.env.generate_address()

    initial_sender_balance = vault.balanceOf(boa.env.eoa)
    initial_receiver_balance = vault.balanceOf(receiver)
    initial_deposited = vault.deposited()
    initial_total_supply = vault.totalSupply()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_amm_rate = amm.rate()

    assert amm.eval("self.rate_time") == 0

    assets = 100 * 10 ** borrowed_token.decimals()

    # Give user tokens and approve vault
    boa.deal(borrowed_token, boa.env.eoa, assets)
    borrowed_token.approve(vault, assets)

    # Check preview matches
    expected_shares = vault.previewDeposit(assets)

    # Increase rate by 1
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Deposit assets with receiver
    shares = vault.deposit(assets, receiver)
    logs = filter_logs(vault, "Deposit")

    # Check shares match preview
    assert shares == expected_shares

    # Check balances - shares go to receiver, not sender
    assert (
        vault.balanceOf(boa.env.eoa) == initial_sender_balance
    )  # Sender balance unchanged
    assert (
        vault.balanceOf(receiver) == initial_receiver_balance + shares
    )  # Receiver gets shares
    assert vault.deposited() == initial_deposited + assets
    assert vault.totalSupply() == initial_total_supply + shares
    assert (
        borrowed_token.balanceOf(controller.address)
        == initial_controller_balance + assets
    )
    assert borrowed_token.balanceOf(boa.env.eoa) == 0

    # Check rate was saved
    assert amm.eval("self.rate_time") > 0
    assert amm.rate() == initial_amm_rate + 1

    # Check event was emitted with correct receiver
    assert len(logs) == 1
    assert logs[0].sender == boa.env.eoa  # Sender is the caller
    assert logs[0].owner == receiver  # Owner is the receiver
    assert logs[0].assets == assets
    assert logs[0].shares == shares


def test_deposit_need_more_assets_revert(vault, controller, amm, borrowed_token):
    """Test deposit reverts with 'Need more assets' when total assets too low."""
    assert vault.totalAssets() == 0

    # Small deposit that would make total assets < MIN_ASSETS
    assets = 1000  # Very small amount
    boa.deal(borrowed_token, boa.env.eoa, assets)
    borrowed_token.approve(vault, assets)

    # Should revert with "Need more assets"
    with boa.reverts("Need more assets"):
        vault.deposit(assets)


def test_deposit_supply_limit_revert(vault, controller, amm, borrowed_token):
    """Test deposit reverts with 'Supply limit' when exceeding max supply."""
    assert vault.totalAssets() == 0

    # Set a low max supply
    max_supply = 100 * 10 ** borrowed_token.decimals()  # Just above current assets
    vault.eval(f"self.maxSupply = {max_supply}")

    # Try to deposit more than allowed
    assets = max_supply + 1  # More than the limit
    boa.deal(borrowed_token, boa.env.eoa, assets)
    borrowed_token.approve(vault, assets)

    # Should revert with "Supply limit"
    with boa.reverts("Supply limit"):
        vault.deposit(assets)
