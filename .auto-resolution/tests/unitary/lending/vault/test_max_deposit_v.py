def test_max_deposit_unlimited(vault):
    """Test maxDeposit when maxSupply is unlimited (MAX_UINT256)."""
    # Ensure maxSupply is unlimited
    vault.eval("self.maxSupply = max_value(uint256)")

    actual_max = vault.maxDeposit(vault.address)
    assert actual_max == vault.eval("max_value(uint256)")


def test_max_deposit_under_limit(vault, controller, amm):
    """Test maxDeposit when maxSupply is limited."""
    total_assets = vault.totalAssets()
    assert total_assets > 0

    # Set a specific max supply
    max_supply = total_assets + 1
    vault.eval(f"self.maxSupply = {max_supply}")

    assert vault.maxDeposit(vault.address) == 1


def test_max_deposit_above_limit(vault, controller, amm):
    """Test maxDeposit when maxSupply is limited."""
    total_assets = vault.totalAssets()
    assert total_assets > 1

    # Set a specific max supply
    max_supply = total_assets - 1
    vault.eval(f"self.maxSupply = {max_supply}")

    assert vault.maxDeposit(vault.address) == 0


def test_max_deposit_at_limit(vault, controller, amm):
    """Test maxDeposit when maxSupply is limited."""
    total_assets = vault.totalAssets()
    assert total_assets > 0

    # Set a specific max supply
    max_supply = total_assets
    vault.eval(f"self.maxSupply = {max_supply}")

    assert vault.maxDeposit(vault.address) == 0
