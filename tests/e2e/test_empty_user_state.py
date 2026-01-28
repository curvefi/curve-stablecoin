import boa


def test_empty_user_state(controller, collateral_token, borrowed_token):
    user = boa.env.eoa

    user_state = controller.user_state(user)
    assert user_state[0] == 0
    assert user_state[1] == 0
    assert user_state[2] == 0
    assert user_state[3] == 0

    # Setup
    collateral_amount = 10 ** collateral_token.decimals()
    debt_amount = 500 * 10 ** borrowed_token.decimals()
    N = 10

    boa.deal(collateral_token, boa.env.eoa, collateral_amount)
    boa.deal(borrowed_token, boa.env.eoa, debt_amount)

    # Create loan
    collateral_token.approve(controller, collateral_amount)
    controller.create_loan(collateral_amount, debt_amount, N)

    user_state = controller.user_state(user)
    assert user_state[0] == collateral_amount
    assert user_state[1] == 0
    assert user_state[2] == debt_amount
    assert user_state[3] == N

    # Repay
    borrowed_token.approve(controller, debt_amount)
    controller.repay(debt_amount)

    user_state = controller.user_state(user)
    assert user_state[0] == 0
    assert user_state[1] == 0
    assert user_state[2] == 0
    assert user_state[3] == 0
