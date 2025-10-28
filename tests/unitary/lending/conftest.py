import pytest
import boa


@pytest.fixture(scope="module")
def market_type():
    return "lending"


@pytest.fixture(scope="module")
def make_debt(vault, controller, amm, borrowed_token):
    borrowed_balance = controller.available_balance()
    debt = borrowed_balance // 2
    assert debt > 0
    rate_mul = int(1.2 * 10**18)
    _total_debt_rate_mul = int(1.1 * 10**18)
    amm.eval(f"self.rate_mul = {rate_mul}")
    controller.eval(f"core._total_debt.initial_debt = {debt}")
    controller.eval(f"core._total_debt.rate_mul = {_total_debt_rate_mul}")


@pytest.fixture(scope="module")
def deposit_into_vault(vault, controller, amm, borrowed_token):
    def f(user=boa.env.eoa, assets=100 * 10 ** borrowed_token.decimals()):
        assert assets > 0
        boa.deal(borrowed_token, user, assets)
        initial_balance = controller.available_balance()
        with boa.env.prank(user):
            borrowed_token.approve(vault, assets)
            vault.deposit(assets)
        assert controller.available_balance() == initial_balance + assets

    return f
