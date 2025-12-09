import pytest


@pytest.fixture(scope="module")
def seed_liquidity():
    """Default liquidity amount used to seed markets at creation time.
    Override in tests to customize seeding.
    """
    return 0


def test_preview_redeem(vault, borrowed_token, deposit_into_vault):
    """Test previewRedeem returns correct assets for given shares."""
    assets = 100 * 10 ** borrowed_token.decimals()
    deposit_into_vault(assets=assets)

    shares = vault.convertToShares(assets)

    assert vault.previewRedeem(shares) == vault.eval(
        f"self._convert_to_assets({shares})"
    )
