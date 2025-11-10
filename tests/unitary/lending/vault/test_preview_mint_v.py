def test_preview_mint(vault, controller, amm, borrowed_token, make_debt):
    """Test previewMint returns correct assets for given shares."""
    shares = 100 * 10 ** borrowed_token.decimals()
    assert vault.previewMint(shares) == vault.eval(
        f"self._convert_to_assets({shares}, False)"
    )
