def test_preview_deposit(vault, controller, amm, borrowed_token, make_debt):
    """Test previewDeposit returns correct shares for given assets."""
    assets = 100 * 10 ** borrowed_token.decimals()
    assert vault.previewDeposit(assets) == vault.eval(
        f"self._convert_to_shares({assets})"
    )
