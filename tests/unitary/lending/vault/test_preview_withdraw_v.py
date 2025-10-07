import boa
import pytest


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 0


def test_preview_withdraw(vault, controller, amm, borrowed_token, deposit_into_vault):
    """Test previewWithdraw returns correct shares for given assets."""
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(assets=assets)

    assert vault.previewWithdraw(assets) == vault.eval(
        f"self._convert_to_shares({assets}, False)"
    )


def test_preview_withdraw_assert_revert(vault, controller, amm, borrowed_token, deposit_into_vault):
    """Test previewWithdraw reverts when assets > borrowed_balance."""
    # Create vault state by depositing
    deposit_into_vault()

    # Try to preview withdraw more than available borrowed_balance
    borrowed_balance = controller.borrowed_balance()
    assets = borrowed_balance + 1  # More than available

    # Should revert due to assert in previewWithdraw
    with boa.reverts():
        vault.previewWithdraw(assets)
