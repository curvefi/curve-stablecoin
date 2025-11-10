def test_asset_returns_borrowed_token(vault, borrowed_token):
    """Test that asset() returns the borrowed token."""
    assert vault.asset() == borrowed_token.address
