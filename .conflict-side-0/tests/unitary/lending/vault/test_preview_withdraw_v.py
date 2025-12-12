import pytest


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 0


def test_preview_withdraw(vault, borrowed_token, deposit_into_vault):
    """Test previewWithdraw returns correct shares for given assets."""
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(assets=assets)

    assert vault.previewWithdraw(assets) == vault.eval(
        f"self._convert_to_shares({assets}, False)"
    )
