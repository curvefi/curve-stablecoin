# TODO test isn't rigorous enough
def test_convert_to_assets(vault, controller, amm, make_debt):
    """Test _convert_to_assets with is_floor=True and False."""
    shares = 100 * 10**18
    total_assets = vault.totalAssets()
    total_supply = vault.totalSupply()
    precision = vault.eval("self.precision")
    dead_shares = vault.eval("DEAD_SHARES")

    # Calculate expected assets (floor)
    numerator = shares * (total_assets * precision + 1)
    denominator = (total_supply + dead_shares) * precision

    expected_assets_floor = numerator // denominator
    actual_assets_floor = vault.eval(f"self._convert_to_assets({shares}, True)")
    assert actual_assets_floor == expected_assets_floor
    # Check that _is_floor=True by default
    assert actual_assets_floor == vault.eval(f"self._convert_to_assets({shares})")
    # Check external method
    assert actual_assets_floor == vault.convertToAssets(shares)

    expected_assets_ceil = (numerator + denominator - 1) // denominator
    actual_assets_ceil = vault.eval(f"self._convert_to_assets({shares}, False)")
    assert actual_assets_ceil == expected_assets_ceil


def test_convert_to_assets_with_total_assets(vault, controller, borrowed_token):
    """Test _convert_to_assets with custom _total_assets parameter."""
    shares = 100 * 10**18
    total_assets = 500 * 10 ** borrowed_token.decimals()
    total_supply = vault.totalSupply()
    precision = vault.eval("self.precision")
    dead_shares = vault.eval("DEAD_SHARES")

    # Calculate expected assets using custom total_assets
    numerator = shares * (total_assets * precision + 1)
    denominator = (total_supply + dead_shares) * precision

    expected_assets_floor = numerator // denominator
    actual_assets_floor = vault.eval(
        f"self._convert_to_assets({shares}, True, {total_assets})"
    )
    assert actual_assets_floor == expected_assets_floor

    expected_assets_ceil = (numerator + denominator - 1) // denominator
    actual_assets_ceil = vault.eval(
        f"self._convert_to_assets({shares}, False, {total_assets})"
    )
    assert actual_assets_ceil == expected_assets_ceil
