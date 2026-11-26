import boa


def test_empty_user_state(
    controller, amm, collateral_token, borrowed_token, price_oracle, admin
):
    user = boa.env.eoa

    # Setup
    N = 10
    collateral_amount = int(0.1 * 10 ** collateral_token.decimals())
    debt_amount = controller.max_borrowable(collateral_amount, N)

    boa.deal(collateral_token, boa.env.eoa, collateral_amount)

    # Create loan
    collateral_token.approve(controller, collateral_amount)
    controller.create_loan(collateral_amount, debt_amount, N)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount, user, True, True)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount, user, True, False)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount, user, False, True)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount, user, False, False)

    # Exchange
    borrowed_token.approve(amm, debt_amount)
    # Collateral is sold only from bands which p_oracle has reached
    p_o = price_oracle.price()
    p_o_down = amm.p_oracle_down(amm.read_user_tick_numbers(user)[1])
    price_oracle.set_price(p_o_down, sender=admin)
    amm.exchange(0, 1, debt_amount, 0)
    price_oracle.set_price(p_o, sender=admin)

    x, _ = amm.get_sum_xy(user)
    assert x > 0

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount - x, user, True, True)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount - x, user, True, False)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount, user, False, True)

    with boa.reverts("Repay amount is too high"):
        controller.repay_health_preview(0, debt_amount, user, False, False)
