def test_total_assets_calculation(vault, controller, amm):
    """Test that _total_assets correctly calculates total assets."""
    # Set specific debt value

    borrowed_balance = controller.available_balance()
    debt = borrowed_balance // 2
    rate_mul = int(1.2 * 10**18)
    _total_debt_rate_mul = int(1.1 * 10**18)
    amm.eval(f"self.rate_mul = {rate_mul}")
    controller.eval(f"core._total_debt.initial_debt = {debt}")
    controller.eval(f"core._total_debt.rate_mul = {_total_debt_rate_mul}")

    expected_total = borrowed_balance + debt * rate_mul // _total_debt_rate_mul
    actual_total = vault.eval("self._total_assets()")

    assert actual_total == expected_total

    # Check that external totalAssets() returns the same as internal _total_assets()
    assert actual_total == vault.totalAssets()
