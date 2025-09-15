import boa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


DEAD_SHARES = 1000


@given(
    collateral_amount=st.integers(min_value=100, max_value=10**20),
    n=st.integers(min_value=4, max_value=50),
    f_p_o=st.floats(min_value=0.7, max_value=1.3),
)
@settings(max_examples=1000)
def test_max_borrowable(
    borrowed_token,
    collateral_token,
    amm,
    controller,
    price_oracle,
    admin,
    collateral_amount,
    n,
    f_p_o,
):
    # Create some liquidity and go into the band
    with boa.env.prank(admin):
        c_amount = 10 ** collateral_token.decimals()
        boa.deal(collateral_token, admin, c_amount)
        collateral_token.approve(controller, 2**256 - 1)
        controller.create_loan(c_amount, controller.max_borrowable(c_amount, 5), 5)
        borrowed_token.approve(amm.address, 2**256 - 1)
        amm.exchange(0, 1, 100, 0)

    # Change oracle
    p_o = int(price_oracle.price() * f_p_o)
    with boa.env.prank(admin):
        price_oracle.set_price(p_o)

    max_borrowable = controller.max_borrowable(collateral_amount, n)
    total = borrowed_token.balanceOf(controller.address)
    if max_borrowable >= total:
        return
    with boa.reverts():
        controller.calculate_debt_n1(
            collateral_amount, int(max_borrowable * 1.001) + n, n
        )
    if max_borrowable == 0:
        return
    controller.calculate_debt_n1(collateral_amount, max_borrowable, n)

    min_collateral = controller.min_collateral(max_borrowable, n)
    assert min_collateral == pytest.approx(
        collateral_amount,
        rel=1e-6
        + (n**2 + n * DEAD_SHARES)
        * (1 / min(min_collateral, collateral_amount) + 1 / max_borrowable),
    )


@given(
    debt_amount=st.integers(min_value=100, max_value=10**20),
    n=st.integers(min_value=4, max_value=50),
    f_p_o=st.floats(min_value=0.7, max_value=1.3),
)
@settings(max_examples=1000)
def test_min_collateral(
    borrowed_token,
    collateral_token,
    amm,
    controller,
    price_oracle,
    admin,
    debt_amount,
    n,
    f_p_o,
):
    # Create some liquidity and go into the band
    with boa.env.prank(admin):
        c_amount = 10 ** collateral_token.decimals()
        boa.deal(collateral_token, admin, c_amount)
        collateral_token.approve(controller, 2**256 - 1)
        controller.create_loan(c_amount, controller.max_borrowable(c_amount, 5), 5)
        borrowed_token.approve(amm.address, 2**256 - 1)
        amm.exchange(0, 1, 10**2, 0)

    # Change oracle
    p_o = int(price_oracle.price() * f_p_o)
    with boa.env.prank(admin):
        price_oracle.set_price(p_o)

    min_collateral = controller.min_collateral(debt_amount, n)

    controller.calculate_debt_n1(min_collateral, debt_amount, n)
