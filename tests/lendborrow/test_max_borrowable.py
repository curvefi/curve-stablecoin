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
def test_max_borrowable(stablecoin, collateral_token, market_amm, market_controller, price_oracle, admin, collateral_amount, n, f_p_o):
    # Create some liquidity and go into the band
    with boa.env.prank(admin):
        collateral_token._mint_for_testing(admin, 10**18)
        collateral_token.approve(market_controller, 2**256-1)
        market_controller.create_loan(10**18, market_controller.max_borrowable(10**18, 5), 5)
        stablecoin.approve(market_amm.address, 2**256-1)
        market_amm.exchange(0, 1, 10**5, 0)

    # Change oracle
    p_o = int(price_oracle.price() * f_p_o)
    with boa.env.prank(admin):
        price_oracle.set_price(p_o)

    max_borrowable = market_controller.max_borrowable(collateral_amount, n)
    with boa.reverts():
        market_controller.calculate_debt_n1(collateral_amount, int(max_borrowable * 1.001) + 1, n)
    if max_borrowable == 0:
        return
    market_controller.calculate_debt_n1(collateral_amount, max_borrowable, n)

    min_collateral = market_controller.min_collateral(max_borrowable, n)
    assert approx(min_collateral, collateral_amount, 1e-6 + (n**2 + n * DEAD_SHARES) / min(min_collateral, collateral_amount))


@given(
    debt_amount=st.integers(min_value=100, max_value=10**20),
    n=st.integers(min_value=4, max_value=50),
    f_p_o=st.floats(min_value=0.7, max_value=1.3))
@settings(max_examples=1000)
def test_min_collateral(stablecoin, collateral_token, market_amm, market_controller, price_oracle, admin, debt_amount, n, f_p_o):
    # Create some liquidity and go into the band
    with boa.env.prank(admin):
        collateral_token._mint_for_testing(admin, 10**18)
        collateral_token.approve(market_controller, 2**256-1)
        market_controller.create_loan(10**18, market_controller.max_borrowable(10**18, 5), 5)
        stablecoin.approve(market_amm.address, 2**256-1)
        market_amm.exchange(0, 1, 10**5, 0)

    # Change oracle
    p_o = int(price_oracle.price() * f_p_o)
    with boa.env.prank(admin):
        price_oracle.set_price(p_o)

    min_collateral = market_controller.min_collateral(debt_amount, n)

    market_controller.calculate_debt_n1(min_collateral, debt_amount, n)
