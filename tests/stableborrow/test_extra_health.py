import boa
from hypothesis import given
from hypothesis import strategies as st


@given(
    extra_health=st.integers(min_value=0, max_value=9 * 10**17),
)
def test_create_loan(
    controller_factory,
    stablecoin,
    collateral_token,
    market_controller,
    market_amm,
    monetary_policy,
    accounts,
    extra_health,
):
    user = accounts[0]

    with boa.env.prank(user):
        initial_amount = 10**7 * 10 ** collateral_token.decimals()
        boa.deal(collateral_token, user, initial_amount)
        c_amount = int(2 * 1e6 * 10 ** collateral_token.decimals() * 1.5 / 3000)
        max_l_amount = market_controller.max_borrowable(c_amount, 5)
        loan_discount = market_controller.loan_discount() / 1e18

        market_controller.set_extra_health(extra_health)
        try:
            market_controller.create_loan(c_amount, max_l_amount, 5)
        except Exception:
            assert extra_health > 0

            l_amount = max(
                int(
                    max_l_amount
                    * (1 - extra_health / 1e18 - loan_discount)
                    / (1 - loan_discount)
                    / 2
                ),
                0,
            )

            if l_amount > 1000:
                market_controller.create_loan(c_amount, l_amount, 5)


@given(
    collateral_amount=st.integers(min_value=10**9, max_value=10**20),
    n=st.integers(min_value=5, max_value=50),
    extra_health=st.integers(min_value=0, max_value=9 * 10**17),
)
def test_max_borrowable(
    market_controller, accounts, collateral_token, collateral_amount, n, extra_health
):
    collateral_amount = collateral_amount // 10 ** (18 - collateral_token.decimals())
    collateral_amount = max(collateral_amount, 1)
    max_borrowable = market_controller.max_borrowable(collateral_amount, n)
    market_controller.calculate_debt_n1(collateral_amount, max_borrowable, n)
    loan_discount = market_controller.loan_discount() / 1e18

    with boa.env.prank(accounts[0]):
        market_controller.set_extra_health(extra_health)
        max_borrowable_user = market_controller.max_borrowable(
            collateral_amount, n, 0, accounts[0]
        )
        if extra_health > 10**16:
            assert max_borrowable_user < max_borrowable
        assert (
            abs(
                max_borrowable_user
                - max(
                    max_borrowable
                    * (1 - extra_health / 1e18 - loan_discount)
                    / (1 - loan_discount),
                    0,
                )
            )
            < 1e-4 * 1e18
        )
        market_controller.calculate_debt_n1(
            collateral_amount, max_borrowable_user, n, accounts[0]
        )
