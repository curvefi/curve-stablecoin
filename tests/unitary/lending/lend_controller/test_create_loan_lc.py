import boa

from tests.utils import max_approve


def test_default_behavior(controller, collateral_token):
    COLLATERAL = 10**23
    DEBT = 10**20
    BANDS = 5

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    max_approve(collateral_token, controller.address)

    assert controller.lent() == 0

    controller.create_loan(COLLATERAL, DEBT, BANDS)

    assert controller.lent() == DEBT
