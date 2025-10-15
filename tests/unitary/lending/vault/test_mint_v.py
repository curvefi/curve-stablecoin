import boa
import pytest
from tests.utils import filter_logs


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 0


def test_mint_basic(vault, controller, amm, monetary_policy, borrowed_token):
    """Test basic mint functionality - balances, rate, event."""
    initial_sender_balance = vault.balanceOf(boa.env.eoa)
    initial_balance = vault.asset_balance()
    initial_total_supply = vault.totalSupply()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_amm_rate = amm.rate()

    assert amm.eval("self.rate_time") == 0

    shares = 100 * 10**18

    # Check preview matches
    expected_assets = vault.previewMint(shares)

    # Give user tokens and approve vault
    boa.deal(borrowed_token, boa.env.eoa, expected_assets)
    borrowed_token.approve(vault, expected_assets)

    # Increase rate by 1
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Mint shares
    assets = vault.mint(shares)
    logs = filter_logs(vault, "Deposit")

    # Check assets match preview
    assert assets == expected_assets

    # Check balances
    assert vault.balanceOf(boa.env.eoa) == initial_sender_balance + shares
    assert vault.asset_balance() == initial_balance + assets
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


def test_mint_with_receiver(vault, controller, amm, monetary_policy, borrowed_token):
    """Test mint with receiver argument - shares go to receiver, not sender."""
    # Generate receiver wallet
    receiver = boa.env.generate_address()

    initial_sender_balance = vault.balanceOf(boa.env.eoa)
    initial_receiver_balance = vault.balanceOf(receiver)
    initial_balance = vault.asset_balance()
    initial_total_supply = vault.totalSupply()
    initial_controller_balance = borrowed_token.balanceOf(controller.address)
    initial_amm_rate = amm.rate()

    assert amm.eval("self.rate_time") == 0

    shares = 100 * 10**18

    # Check preview matches
    expected_assets = vault.previewMint(shares)

    # Give user tokens and approve vault
    boa.deal(borrowed_token, boa.env.eoa, expected_assets)
    borrowed_token.approve(vault, expected_assets)

    # Increase rate by 1
    monetary_policy.set_rate(initial_amm_rate + 1)

    # Mint shares with receiver
    assets = vault.mint(shares, receiver)
    logs = filter_logs(vault, "Deposit")

    # Check assets match preview
    assert assets == expected_assets

    # Check balances - shares go to receiver, not sender
    assert (
        vault.balanceOf(boa.env.eoa) == initial_sender_balance
    )  # Sender balance unchanged
    assert (
        vault.balanceOf(receiver) == initial_receiver_balance + shares
    )  # Receiver gets shares
    assert vault.asset_balance() == initial_balance + assets
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


def test_mint_need_more_assets_revert(vault, controller, amm, borrowed_token):
    """Test mint reverts with 'Need more assets' when total assets too low."""
    assert vault.totalAssets() == 0

    # Small mint that would make total assets < MIN_ASSETS
    assets = vault.eval("MIN_ASSETS") - 1
    shares = vault.convertToShares(assets)  # Very small amount
    boa.deal(borrowed_token, boa.env.eoa, assets)
    borrowed_token.approve(vault, assets)

    # Should revert with "Need more assets"
    with boa.reverts("Need more assets"):
        vault.mint(shares)


def test_mint_supply_limit_revert(vault, controller, amm, borrowed_token):
    """Test mint reverts with 'Supply limit' when exceeding max supply."""
    assert vault.totalAssets() == 0

    # Set a low max supply
    max_supply = 100 * 10 ** borrowed_token.decimals()  # Just above current assets
    vault.eval(f"self.maxSupply = {max_supply}")

    # Try to mint more than allowed
    shares = vault.maxMint(boa.env.eoa) + 1  # More than the limit
    expected_assets = vault.previewMint(shares)
    boa.deal(borrowed_token, boa.env.eoa, expected_assets)
    borrowed_token.approve(vault, expected_assets)

    # Should revert with "Supply limit"
    with boa.reverts("Supply limit"):
        vault.mint(shares)
