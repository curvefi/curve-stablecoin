"""
Minimal PoC: Low decimals don’t accrue interest
"""

import boa
import pytest
from tests.utils import max_approve


@pytest.fixture(scope="module")
def market_type():
    return "lending"


@pytest.fixture(scope="module")
def borrowed_decimals():
    return 2


@pytest.fixture(scope="module")
def collateral_decimals():
    return 18


def test_low_decimals_do_not_accrue_interest(
    vault,
    controller,
    amm,
    monetary_policy,
    borrowed_token,
    collateral_token,
    admin,
    accounts,
):
    user = accounts[0]
    n_blocks = 3 * 24 * 3600 // 12  # 3 days
    initial_debt = 100 * 10 ** borrowed_token.decimals()
    collateral_amount = 10 ** collateral_token.decimals()

    monetary_policy.set_rate(1585489599, sender=admin)  # 5% APR

    with boa.env.prank(user):
        boa.deal(collateral_token, user, collateral_amount)
        max_approve(collateral_token, controller.address)
        controller.create_loan(collateral_amount, initial_debt, 30)

    # 1. Accrues interest without actions over a long period of time
    with boa.env.anchor():
        boa.env.time_travel(n_blocks * 12)
        default_debt = controller.debt(user)
        assert default_debt > initial_debt

    # 2. Does not accrue interest repaying and creating loan again
    #    every 2 minutes in case it's the only borrower in the market.
    with boa.env.anchor():
        with boa.env.prank(user):
            extra_debt = 0
            boa.deal(borrowed_token, user, initial_debt + n_blocks // 100)
            max_approve(borrowed_token, controller.address)
            for i in range(n_blocks // 100):
                boa.env.time_travel(12 * 100)
                assert controller.debt(user) == initial_debt + 1
                controller.repay(initial_debt + 1)
                extra_debt += 1
                controller.create_loan(collateral_amount, initial_debt, 30)

        assert controller.debt(user) == initial_debt
        assert extra_debt == n_blocks // 100
        assert initial_debt + extra_debt > default_debt

    # 3. Debt is rounded up in case there are 2 borrowers in the market.
    #    Repay-and-Create trick only increases the debt.
    with boa.env.anchor():
        user2 = accounts[1]
        with boa.env.prank(user2):
            boa.deal(collateral_token, user2, collateral_amount)
            max_approve(collateral_token, controller.address)
            controller.create_loan(collateral_amount, initial_debt, 30)

        with boa.env.prank(user):
            extra_debt = 0
            boa.deal(borrowed_token, user, initial_debt + n_blocks // 100)
            max_approve(borrowed_token, controller.address)
            for i in range(n_blocks // 100):
                boa.env.time_travel(12 * 100)
                assert controller.debt(user) == initial_debt + 1
                controller.repay(initial_debt + 1)
                extra_debt += 1
                controller.create_loan(collateral_amount, initial_debt, 30)

        assert controller.debt(user) == initial_debt
        assert extra_debt == n_blocks // 100
        assert initial_debt + extra_debt > default_debt
