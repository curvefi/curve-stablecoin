def test_lend_apr_calculation(vault, amm, controller):
    """Test that lend_apr correctly calculates lending APR."""
    test_rate = 10**9
    borrowed_balance = controller.borrowed_balance()
    assert borrowed_balance > 0
    debt = borrowed_balance // 2

    amm.eval(f"self.rate = {test_rate}")
    controller.eval(f"core._total_debt.initial_debt = {debt}")

    seconds_in_year = 365 * 86400
    expected_apr = test_rate * seconds_in_year * debt // (debt + borrowed_balance)

    actual_apr = vault.lend_apr()
    assert actual_apr == expected_apr
