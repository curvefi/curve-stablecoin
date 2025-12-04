def test_max_mint_unlimited(vault):
    """Test maxMint when maxSupply is unlimited (MAX_UINT256)."""
    # Ensure maxSupply is unlimited
    vault.eval("self.maxSupply = max_value(uint256)")

    actual_max = vault.maxMint(vault.address)
    assert actual_max == vault.eval("max_value(uint256)")


def test_max_mint_under_limit(vault, controller, amm, borrowed_token):
    """Test maxMint when maxSupply is limited."""
    total_assets = vault.totalAssets()
    assert total_assets > 0

    # Set a specific max supply
    assets = 100 * borrowed_token.decimals()
    max_supply = total_assets + assets
    vault.eval(f"self.maxSupply = {max_supply}")

    assert vault.maxMint(vault.address) == vault.convertToShares(assets)


def test_max_mint_above_limit(vault, controller, amm):
    """Test maxMint when maxSupply is limited."""
    total_assets = vault.totalAssets()
    assert total_assets > 1

    # Set a specific max supply
    max_supply = total_assets - 1
    vault.eval(f"self.maxSupply = {max_supply}")

    assert vault.maxMint(vault.address) == 0


def test_max_mint_at_limit(vault, controller, amm):
    """Test maxMint when maxSupply is limited."""
    total_assets = vault.totalAssets()
    assert total_assets > 0

    # Set a specific max supply
    max_supply = total_assets
    vault.eval(f"self.maxSupply = {max_supply}")

    assert vault.maxMint(vault.address) == 0
