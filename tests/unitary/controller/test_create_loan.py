import boa

from tests.utils.constants import WAD

BORROW_CAP = 10**9
COLLATERAL = 10**21
N_BANDS = 5


def test_borrow_cap_reverts_when_exceeded(controller, collateral_token):
    controller.eval(f"core.borrow_cap = {BORROW_CAP}")
    controller.eval(f"core._total_debt.initial_debt = {BORROW_CAP}")
    controller.eval(f"core._total_debt.rate_mul = {WAD}")

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    collateral_token.approve(controller, 2**256 - 1)

    with boa.reverts("Borrow cap exceeded"):
        controller.create_loan(COLLATERAL, 1, N_BANDS)
