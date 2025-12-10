import boa

LIQUIDATION_DISCOUNT = 2 * 10**17 
LOAN_DISCOUNT = 5 * 10**17

def test_default_behavior(controller, admin):
    controller.set_borrowing_discounts(LOAN_DISCOUNT, LIQUIDATION_DISCOUNT, sender=admin)

def test_only_admin(controller):
    with boa.reverts("only admin"):
        controller.set_borrowing_discounts(LOAN_DISCOUNT, LIQUIDATION_DISCOUNT)

        