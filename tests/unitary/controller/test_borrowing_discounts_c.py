import boa

LIQUIDATION_DISCOUNT = 2 * 10**17
LOAN_DISCOUNT = 5 * 10**17


def test_default_behavior(controller, configurator, admin):
    configurator.set_borrowing_discounts(
        controller, LOAN_DISCOUNT, LIQUIDATION_DISCOUNT, sender=admin
    )


def test_only_admin(controller, configurator):
    with boa.reverts("Not authorized for this controller"):
        configurator.set_borrowing_discounts(
            controller, LOAN_DISCOUNT, LIQUIDATION_DISCOUNT
        )


def test_revert_liquidation_discount_zero(controller, configurator, admin):
    with boa.reverts("liquidation discount = 0"):
        configurator.set_borrowing_discounts(controller, LOAN_DISCOUNT, 0, sender=admin)


def test_revert_loan_discount_greater_or_equal_to_one(controller, configurator, admin):
    with boa.reverts("loan discount >= 100%"):
        configurator.set_borrowing_discounts(
            controller, 10**18, LIQUIDATION_DISCOUNT, sender=admin
        )

    with boa.reverts("loan discount >= 100%"):
        configurator.set_borrowing_discounts(
            controller, 10**18 + 1, LIQUIDATION_DISCOUNT, sender=admin
        )


def test_revert_loan_discount_less_or_equal_to_liquidation_discount(
    controller, configurator, admin
):
    with boa.reverts("loan discount <= liquidation discount"):
        configurator.set_borrowing_discounts(
            controller, LIQUIDATION_DISCOUNT, LOAN_DISCOUNT, sender=admin
        )

    with boa.reverts("loan discount <= liquidation discount"):
        configurator.set_borrowing_discounts(
            controller, LIQUIDATION_DISCOUNT, LIQUIDATION_DISCOUNT, sender=admin
        )
