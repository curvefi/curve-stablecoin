import boa

from tests.utils import max_approve


def test_default_behavior(controller, collateral_token):
    COLLATERAL = 10**23
    INITIAL_DEBT = 10**20
    EXTRA_COLLATERAL = 10**22
    EXTRA_DEBT = 10**19
    BANDS = 5

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL + EXTRA_COLLATERAL)
    max_approve(collateral_token, controller.address)

    assert controller.lent() == 0

    controller.create_loan(COLLATERAL, INITIAL_DEBT, BANDS)
    assert controller.lent() == INITIAL_DEBT

    controller.borrow_more(EXTRA_COLLATERAL, EXTRA_DEBT)

    assert controller.lent() == INITIAL_DEBT + EXTRA_DEBT
