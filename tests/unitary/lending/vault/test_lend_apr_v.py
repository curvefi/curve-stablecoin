def test_lend_apr_calculation(vault, amm, controller):
    """Test that lend_apr correctly calculates lending APR."""
    rate = 10**9
    borrowed_balance = controller.borrowed_balance()
    assert borrowed_balance > 0

    debt = borrowed_balance // 2
    rate_mul = int(1.2 * 10**18)
    _total_debt_rate_mul = int(1.1 * 10**18)
    amm.eval(f"self.rate_mul = {rate_mul}")
    controller.eval(f"core._total_debt.initial_debt = {debt}")
    controller.eval(f"core._total_debt.rate_mul = {_total_debt_rate_mul}")
    amm.eval(f"self.rate = {rate}")

    seconds_in_year = 365 * 86400
    debt = debt * rate_mul // _total_debt_rate_mul
    expected_apr = rate * seconds_in_year * debt // (debt + borrowed_balance)

    actual_apr = vault.lend_apr()
    assert actual_apr == expected_apr
