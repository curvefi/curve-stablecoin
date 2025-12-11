from textwrap import dedent
import boa
import pytest

from tests.utils import filter_logs


@pytest.fixture(scope="module", autouse=True)
def expose_internal(controller):
    controller.inject_function(
        dedent(
            """
        @external
        def set_borrowing_discounts(
            _loan_discount: uint256,
            _liquidation_discount: uint256
        ):
            core._set_borrowing_discounts(
                _loan_discount,
                _liquidation_discount
            )
        """
        )
    )


LIQUIDATION_DISCOUNT = 2 * 10**17
LOAN_DISCOUNT = 5 * 10**17


def test_default_behavior(controller):
    controller.inject.set_borrowing_discounts(LOAN_DISCOUNT, LIQUIDATION_DISCOUNT)
    logs = filter_logs(controller, "SetBorrowingDiscounts")

    assert len(logs) == 1
    assert logs[0].loan_discount == LOAN_DISCOUNT
    assert logs[0].liquidation_discount == LIQUIDATION_DISCOUNT

    assert controller.loan_discount() == LOAN_DISCOUNT
    assert controller.liquidation_discount() == LIQUIDATION_DISCOUNT


def test_revert_liquidation_discount_zero(controller):
    with boa.reverts(dev="liquidation discount = 0"):
        controller.inject.set_borrowing_discounts(LOAN_DISCOUNT, 0)


def test_revert_loan_discount_greater_or_equal_to_one(controller):
    with boa.reverts(dev="loan discount >= 100%"):
        controller.inject.set_borrowing_discounts(10**18, LIQUIDATION_DISCOUNT)

    with boa.reverts(dev="loan discount >= 100%"):
        controller.inject.set_borrowing_discounts(10**18 + 1, LIQUIDATION_DISCOUNT)


def test_revert_loan_discount_less_or_equal_to_liquidation_discount(controller):
    with boa.reverts(dev="loan discount <= liquidation discount"):
        controller.inject.set_borrowing_discounts(LIQUIDATION_DISCOUNT, LOAN_DISCOUNT)

    with boa.reverts(dev="loan discount <= liquidation discount"):
        controller.inject.set_borrowing_discounts(LIQUIDATION_DISCOUNT, LIQUIDATION_DISCOUNT)
