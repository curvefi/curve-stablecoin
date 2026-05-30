from tests.utils.constants import WAD


def test_lend_apr_calculation(vault, amm, controller, admin_percentage):
    """Test that lend_apr correctly calculates lending APR net of admin fees."""
    borrowed_balance = controller.available_balance()
    assert borrowed_balance > 0

    debt = borrowed_balance // 2
    rate = 10**9
    rate_mul = int(1.2 * 10**18)
    _total_debt_rate_mul = int(1.1 * 10**18)

    controller.eval(f"core._total_debt.initial_debt = {debt}")
    controller.eval(f"core._total_debt.rate_mul = {_total_debt_rate_mul}")
    amm.eval(f"self.rate_mul = {rate_mul}")
    amm.eval(f"self.rate = {rate}")

    seconds_in_year = 365 * 86400
    admin_fees = (
        (debt * rate_mul // _total_debt_rate_mul - debt) * admin_percentage // WAD
    )
    debt = debt * rate_mul // _total_debt_rate_mul
    gross_apr = rate * seconds_in_year * debt // (borrowed_balance + debt - admin_fees)
    expected_apr = gross_apr * (WAD - admin_percentage) // WAD

    actual_apr = vault.lend_apr()
    assert actual_apr == expected_apr
