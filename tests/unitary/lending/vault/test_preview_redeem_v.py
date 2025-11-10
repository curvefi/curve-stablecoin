import boa
import pytest


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 0


def test_preview_redeem(vault, controller, amm, borrowed_token, deposit_into_vault):
    """Test previewRedeem returns correct assets for given shares."""
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(assets=assets)

    shares = vault.convertToShares(assets)

    assert vault.previewRedeem(shares) == vault.eval(
        f"self._convert_to_assets({shares})"
    )


def test_preview_redeem_assert_revert(
    vault, controller, amm, borrowed_token, deposit_into_vault
):
    """Test previewRedeem reverts when assets > borrowed_balance."""
    # Create vault state by depositing
    deposit_into_vault()

    # Try to preview redeem more than available borrowed_balance
    borrowed_balance = controller.available_balance()
    shares = vault.convertToShares(borrowed_balance + 1)  # More than available

    # Should revert due to assert in previewRedeem
    with boa.reverts():
        vault.previewRedeem(shares)


def test_preview_redeem_zero_supply(vault, controller, amm, borrowed_token):
    """Test previewRedeem when totalSupply is 0."""
    # Vault has no shares
    assert vault.totalSupply() == 0

    # Should return 0 for any shares
    assert vault.previewRedeem(0) == 0

    # Should revert for non-zero shares
    with boa.reverts():
        vault.previewRedeem(1)
