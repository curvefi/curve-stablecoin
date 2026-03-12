import boa


def test_increases_after_deposit(controller, borrowed_token):
    assert controller.available_balance() == borrowed_token.balanceOf(controller)
    boa.deal(borrowed_token, controller, controller.available_balance() + 1)
    assert controller.available_balance() == borrowed_token.balanceOf(controller)
