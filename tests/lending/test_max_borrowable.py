import boa
from hypothesis import given, settings
from hypothesis import strategies as st
from ..conftest import approx


DEAD_SHARES = 1000


@given(
    collateral_amount=st.integers(min_value=100, max_value=10**20),
    n=st.integers(min_value=4, max_value=50),
    f_p_o=st.floats(min_value=0.7, max_value=1.3))
@settings(max_examples=1000)
def test_max_borrowable(borrowed_token, collateral_token, market_amm, filled_controller, price_oracle, admin,
                        collateral_amount, n, f_p_o):
    # Create some liquidity and go into the band
    with boa.env.prank(admin):
        c_amount = 10**collateral_token.decimals()
        collateral_token._mint_for_testing(admin, c_amount)
        collateral_token.approve(filled_controller, 2**256-1)
        filled_controller.create_loan(c_amount, filled_controller.max_borrowable(c_amount, 5), 5)
        borrowed_token.approve(market_amm.address, 2**256-1)
        market_amm.exchange(0, 1, 100, 0)

    # Change oracle
    p_o = int(price_oracle.price() * f_p_o)
    with boa.env.prank(admin):
        price_oracle.set_price(p_o)

    max_borrowable = filled_controller.max_borrowable(collateral_amount, n)
    total = borrowed_token.balanceOf(filled_controller.address)
    if max_borrowable >= total:
        return
    with boa.reverts():
        filled_controller.calculate_debt_n1(collateral_amount, int(max_borrowable * 1.001) + n, n)
    if max_borrowable == 0:
        return
    filled_controller.calculate_debt_n1(collateral_amount, max_borrowable, n)

    min_collateral = filled_controller.min_collateral(max_borrowable, n)
    assert approx(min_collateral,
                  collateral_amount, 1e-6 + (n**2 + n * DEAD_SHARES) * (
                      1 / min(min_collateral, collateral_amount) + 1 / max_borrowable))


@given(
    debt_amount=st.integers(min_value=100, max_value=10**20),
    n=st.integers(min_value=4, max_value=50),
    f_p_o=st.floats(min_value=0.7, max_value=1.3))
@settings(max_examples=1000)
def test_min_collateral(borrowed_token, collateral_token, market_amm, filled_controller, price_oracle, admin,
                        debt_amount, n, f_p_o):
    # Create some liquidity and go into the band
    with boa.env.prank(admin):
        c_amount = 10**collateral_token.decimals()
        collateral_token._mint_for_testing(admin, c_amount)
        collateral_token.approve(filled_controller, 2**256-1)
        filled_controller.create_loan(c_amount, filled_controller.max_borrowable(c_amount, 5), 5)
        borrowed_token.approve(market_amm.address, 2**256-1)
        market_amm.exchange(0, 1, 10**2, 0)

    # Change oracle
    p_o = int(price_oracle.price() * f_p_o)
    with boa.env.prank(admin):
        price_oracle.set_price(p_o)

    min_collateral = filled_controller.min_collateral(debt_amount, n)

    filled_controller.calculate_debt_n1(min_collateral, debt_amount, n)
