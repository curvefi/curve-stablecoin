def test_price_per_share(vault, controller, amm, make_debt):
    """Test pricePerShare with is_floor=True and False."""
    total_assets = vault.totalAssets()
    total_supply = vault.totalSupply()
    precision = vault.eval("self.precision")
    dead_shares = vault.eval("DEAD_SHARES")

    # Calculate expected price per share (floor)
    numerator = 10**18 * (total_assets * precision + 1)
    denominator = total_supply + dead_shares

    expected_pps_floor = numerator // denominator
    actual_pps_floor = vault.pricePerShare(True)
    assert actual_pps_floor == expected_pps_floor
    # Check that _is_floor=True by default
    assert actual_pps_floor == vault.pricePerShare()
    # Check that it's a view function
    assert actual_pps_floor == vault.pricePerShare(True)

    expected_pps_ceil = (numerator + denominator - 1) // denominator
    actual_pps_ceil = vault.pricePerShare(False)
    assert actual_pps_ceil == expected_pps_ceil


def test_price_per_share_zero_supply(vault):
    """Test pricePerShare when totalSupply is zero."""
    # Ensure zero supply
    vault.eval("self.totalSupply = 0")

    expected_pps = 10**18 // vault.eval("DEAD_SHARES")
    actual_pps = vault.pricePerShare()
    assert actual_pps == expected_pps
