def test_borrow_apr_calculation(vault, amm):
    """Test that borrow_apr correctly calculates annualized rate from AMM rate."""
    test_rate = 10**9
    amm.eval(f"self.rate = {10**9}")
    seconds_in_year = 365 * 86400  # 31,536,000 seconds
    expected_apr = test_rate * seconds_in_year

    actual_apr = vault.borrow_apr()
    assert actual_apr == expected_apr
