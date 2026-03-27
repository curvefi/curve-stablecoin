import boa

from tests.utils import max_approve

N_BANDS = 6


def test_repay_health_preview_zero_d_debt(
    controller, collateral_token, borrowed_token
):
    """
    Test that repay_health_preview reverts when _d_debt is 0.
    """
    borrower = boa.env.eoa
    collateral_amount = int(N_BANDS * 0.05 * 10 ** collateral_token.decimals())
    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    max_approve(borrowed_token, controller)
    controller.create_loan(collateral_amount, 10 ** borrowed_token.decimals(), N_BANDS)

    with boa.reverts("No coins to repay"):
        controller.repay_health_preview(0, 0, borrower, borrower, False, False)
