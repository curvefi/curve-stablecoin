# You can access update_total_debt using

import boa
import pytest
from textwrap import dedent

from tests.utils.constants import WAD


BORROW_CAP = 10**9


@pytest.fixture(scope="module", autouse=True)
def expose_internal(controller):
    controller.inject_function(
        dedent("""
        @external
        def update_total_debt(d_debt: uint256, rate_mul: uint256, is_increase: bool) -> core.IController.Loan:
            return core._update_total_debt(d_debt, rate_mul, is_increase)
        """)
    )


def test_default_behavior(controller):
    controller.eval("core._total_debt.initial_debt = 0")
    controller.eval(f"core._total_debt.rate_mul = {WAD}")
    controller.eval(f"core.borrow_cap = {BORROW_CAP}")

    controller.inject.update_total_debt(BORROW_CAP - 1, WAD, True)
    current_debt = controller.eval("core._total_debt.initial_debt")
    assert current_debt == BORROW_CAP - 1

    controller.inject.update_total_debt(1, WAD, True)
    current_debt = controller.eval("core._total_debt.initial_debt")
    assert current_debt == BORROW_CAP


def test_exceeding_borrow_cap_reverts(controller):
    controller.eval(f"core._total_debt.rate_mul = {WAD}")
    controller.eval(f"core.borrow_cap = {BORROW_CAP}")
    controller.eval(f"core._total_debt.initial_debt = {BORROW_CAP}")

    with boa.reverts("Borrow cap exceeded"):
        controller.inject.update_total_debt(1, WAD, True)

    current_debt = controller.eval("core._total_debt.initial_debt")
    assert current_debt == BORROW_CAP
