def test_preview_deposit(vault, controller, amm, borrowed_token):
    """Test previewDeposit returns correct shares for given assets."""
    # Set up some assets in the vault
    borrowed_balance = controller.borrowed_balance()
    debt_value = borrowed_balance // 2
    rate_mul = int(1.2 * 10**18)
    _total_debt_rate_mul = int(1.1 * 10**18)
    amm.eval(f"self.rate_mul = {rate_mul}")
    controller.eval(f"core._total_debt.initial_debt = {debt_value}")
    controller.eval(f"core._total_debt.rate_mul = {_total_debt_rate_mul}")

    assets = 100 * 10 ** borrowed_token.decimals()
    assert vault.previewDeposit(assets) == vault.eval(
        f"self._convert_to_shares({assets})"
    )
