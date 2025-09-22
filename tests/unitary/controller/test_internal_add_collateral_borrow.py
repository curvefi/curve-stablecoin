import boa
import pytest
from textwrap import dedent

from tests.utils.constants import MAX_UINT256, WAD


BORROW_CAP = 10**9
COLLATERAL = 10**21
N_BANDS = 5


@pytest.fixture(scope="module", autouse=True)
def expose_internal(controller):
    controller.inject_function(
        dedent(
            """
        @external
        def add_collateral_borrow(
            d_collateral: uint256,
            d_debt: uint256,
            _for: address,
            remove_collateral: bool,
            check_rounding: bool,
        ):
            core._add_collateral_borrow(
                d_collateral, d_debt, _for, remove_collateral, check_rounding
            )
        """
        )
    )


def test_borrow_cap_reverts(controller, collateral_token):
    controller.eval("core._total_debt.initial_debt = 0")
    controller.eval(f"core._total_debt.rate_mul = {WAD}")
    controller.eval(f"core.borrow_cap = {BORROW_CAP}")

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    collateral_token.approve(controller, MAX_UINT256)

    debt = BORROW_CAP - 1

    controller.create_loan(COLLATERAL, debt, N_BANDS)

    controller.eval(f"core.borrow_cap = {debt}")
    controller.eval(f"core._total_debt.initial_debt = {debt}")
    controller.eval(f"core._total_debt.rate_mul = {WAD}")

    with boa.reverts("Borrow cap exceeded"):
        controller.inject.add_collateral_borrow(0, 1, boa.env.eoa, False, False)
