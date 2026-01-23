import boa


def test_empty_user_state(controller, amm, collateral_token, borrowed_token):
    user = boa.env.eoa

    # Setup
    N = 10
    collateral_amount = int(0.1 * 10 ** collateral_token.decimals())
    debt_amount = controller.max_borrowable(collateral_amount, N)
    print(debt_amount)

    boa.deal(collateral_token, boa.env.eoa, collateral_amount)

    # Create loan
    collateral_token.approve(controller, collateral_amount)
    controller.create_loan(collateral_amount, debt_amount, N)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount, user, user, True, True)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount, user, user, True, False)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount, user, user, False, True)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount, user, user, False, False)

    # Exchange
    borrowed_token.approve(amm, debt_amount)
    amm.exchange(0, 1, debt_amount, 0)

    x, _ = amm.get_sum_xy(user)
    assert x > 0

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount - x, user, user, True, True)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount - x, user, user, True, False)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount - x, user, user, False, True)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount - x, user, user, False, False)
