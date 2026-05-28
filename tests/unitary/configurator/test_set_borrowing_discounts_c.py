import boa
import pytest


LIQUIDATION_DISCOUNT = 2 * 10**17
LOAN_DISCOUNT = 5 * 10**17
CUSTOM_ADMIN_LIQUIDATION_DISCOUNT = 15 * 10**16
CUSTOM_ADMIN_LOAN_DISCOUNT = 45 * 10**16
CONFIGURE_TRACKING_CONTROLLER = """
# pragma version 0.4.3

configure_calls: public(uint256)

@external
def configure(
    _loan_discount: uint256,
    _liquidation_discount: uint256,
    _monetary_policy: address,
    _new_view_impl: address,
    _debt_ceiling: uint256,
    _price_oracle: address,
    _callback: address,
):
    self.configure_calls += 1
"""


@pytest.fixture
def configure_tracking_controller():
    return boa.loads(CONFIGURE_TRACKING_CONTROLLER)


def test_set_borrowing_discounts_updates_controller_discounts(
    configurator, controller, admin
):
    assert controller.loan_discount() != LOAN_DISCOUNT
    assert controller.liquidation_discount() != LIQUIDATION_DISCOUNT

    configurator.set_borrowing_discounts(
        controller, LOAN_DISCOUNT, LIQUIDATION_DISCOUNT, sender=admin
    )

    assert controller.loan_discount() == LOAN_DISCOUNT
    assert controller.liquidation_discount() == LIQUIDATION_DISCOUNT


def test_set_borrowing_discounts_emits_set_borrowing_discounts(
    configurator, controller, admin, single_configurator_event
):
    configurator.set_borrowing_discounts(
        controller, LOAN_DISCOUNT, LIQUIDATION_DISCOUNT, sender=admin
    )

    log = single_configurator_event(configurator, "SetBorrowingDiscounts")

    assert log.controller == controller.address
    assert log.loan_discount == LOAN_DISCOUNT
    assert log.liquidation_discount == LIQUIDATION_DISCOUNT


def test_set_borrowing_discounts_allows_controller_custom_admin(
    configurator, controller, admin
):
    custom_admin = boa.env.generate_address("custom_admin")

    configurator.set_custom_admin(controller, custom_admin, sender=admin)
    configurator.set_borrowing_discounts(
        controller,
        CUSTOM_ADMIN_LOAN_DISCOUNT,
        CUSTOM_ADMIN_LIQUIDATION_DISCOUNT,
        sender=custom_admin,
    )

    assert controller.loan_discount() == CUSTOM_ADMIN_LOAN_DISCOUNT
    assert controller.liquidation_discount() == CUSTOM_ADMIN_LIQUIDATION_DISCOUNT


def test_set_borrowing_discounts_reverts_liquidation_discount_zero(
    configurator, admin, configure_tracking_controller
):
    with boa.reverts("liquidation discount = 0"):
        configurator.set_borrowing_discounts(
            configure_tracking_controller, LOAN_DISCOUNT, 0, sender=admin
        )

    assert configure_tracking_controller.configure_calls() == 0


def test_set_borrowing_discounts_reverts_loan_discount_gte_wad(
    configurator, admin, configure_tracking_controller
):
    for loan_discount in (10**18, 10**18 + 1):
        with boa.reverts("loan discount >= 100%"):
            configurator.set_borrowing_discounts(
                configure_tracking_controller,
                loan_discount,
                LIQUIDATION_DISCOUNT,
                sender=admin,
            )

    assert configure_tracking_controller.configure_calls() == 0


def test_set_borrowing_discounts_reverts_loan_discount_lte_liquidation_discount(
    configurator, admin, configure_tracking_controller
):
    for loan_discount in (LIQUIDATION_DISCOUNT, LIQUIDATION_DISCOUNT - 1):
        with boa.reverts("loan discount <= liquidation discount"):
            configurator.set_borrowing_discounts(
                configure_tracking_controller,
                loan_discount,
                LIQUIDATION_DISCOUNT,
                sender=admin,
            )

    assert configure_tracking_controller.configure_calls() == 0


def test_set_borrowing_discounts_reverts_unauthorized(configurator, controller):
    non_admin = boa.env.generate_address("non_admin")

    with boa.reverts("Not authorized for this controller"):
        configurator.set_borrowing_discounts(
            controller, LOAN_DISCOUNT, LIQUIDATION_DISCOUNT, sender=non_admin
        )
