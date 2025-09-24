def test_convert_to_shares(vault, controller, amm):
    """Test _convert_to_shares with is_floor=True (default)."""
    # Set up some assets in the vault
    borrowed_balance = controller.borrowed_balance()
    debt_value = borrowed_balance // 2

    rate_mul = int(1.2 * 10**18)
    _total_debt_rate_mul = int(1.1 * 10**18)
    amm.eval(f"self.rate_mul = {rate_mul}")
    controller.eval(f"core._total_debt.initial_debt = {debt_value}")
    controller.eval(f"core._total_debt.rate_mul = {_total_debt_rate_mul}")

    assets = 100 * 10**18
    total_assets = vault.totalAssets()
    total_supply = vault.totalSupply()
    precision = vault.eval("self.precision")
    dead_shares = vault.eval("DEAD_SHARES")

    # Calculate expected shares (floor)
    numerator = (total_supply + dead_shares) * assets * precision
    denominator = total_assets * precision + 1

    expected_shares_floor = numerator // denominator
    actual_shares_floor = vault.eval(f"self._convert_to_shares({assets}, True)")
    assert actual_shares_floor == expected_shares_floor
    # Check that _is_floor=True by default
    assert actual_shares_floor == vault.eval(f"self._convert_to_shares({assets})")
    # Check external method
    assert actual_shares_floor == vault.convertToShares(assets)

    expected_shares_ceil = (numerator + denominator - 1) // denominator
    actual_shares_ceil = vault.eval(f"self._convert_to_shares({assets}, False)")
    assert actual_shares_ceil == expected_shares_ceil


def test_convert_to_shares_with_total_assets(vault, controller, borrowed_token):
    """Test _convert_to_shares with custom _total_assets parameter."""
    # Set up some assets in the vault
    borrowed_balance = controller.borrowed_balance()
    debt_value = borrowed_balance // 2
    controller.eval(f"core._total_debt.initial_debt = {debt_value}")

    assets = 100 * 10**18
    total_assets = 500 * 10**borrowed_token.decimals()
    total_supply = vault.totalSupply()
    precision = vault.eval("self.precision")
    dead_shares = vault.eval("DEAD_SHARES")

    # Calculate expected shares using custom total_assets
    numerator = (total_supply + dead_shares) * assets * precision
    denominator = total_assets * precision + 1

    expected_shares_floor = numerator // denominator
    actual_shares_floor = vault.eval(f"self._convert_to_shares({assets}, True, {total_assets})")
    assert actual_shares_floor == expected_shares_floor

    expected_shares_ceil = (numerator + denominator - 1) // denominator
    actual_shares_ceil = vault.eval(f"self._convert_to_shares({assets}, False, {total_assets})")
    assert actual_shares_ceil == expected_shares_ceil
