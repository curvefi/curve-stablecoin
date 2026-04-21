import boa
from tests.utils.deployers import LM_CALLBACK_WITH_REVERTS_DEPLOYER
from tests.utils.constants import MAX_UINT256, ZERO_ADDRESS

WEEK = 7 * 86400


def test_add_new_lm_callback(
    admin,
    trader,
    collateral_token,
    borrowed_token,
    controller,
    amm,
    gauge_controller,
):
    borrower = boa.env.generate_address("borrower")
    boa.deal(collateral_token, borrower, 10**22)
    collateral_token.approve(controller, MAX_UINT256, sender=borrower)

    # Remove current LM Callback
    controller.set_callback(ZERO_ADDRESS, sender=admin)

    boa.env.time_travel(seconds=2 * WEEK + 5)

    borrower_balances0 = [
        borrowed_token.balanceOf(borrower),
        collateral_token.balanceOf(borrower),
    ]
    trader_balances0 = [borrowed_token.balanceOf(trader), collateral_token.balanceOf(trader)]

    # Market interactions
    controller.create_loan(10**21, 10**21 * 2600, 10, sender=borrower)
    amm.exchange(0, 1, 10**20, 0, sender=trader)

    borrower_balances1 = [
        borrowed_token.balanceOf(borrower),
        collateral_token.balanceOf(borrower),
    ]
    trader_balances1 = [borrowed_token.balanceOf(trader), collateral_token.balanceOf(trader)]

    assert borrower_balances1[0] - borrower_balances0[0] == 10**21 * 2600
    assert borrower_balances0[1] - borrower_balances1[1] == 10**21
    assert trader_balances0[0] > trader_balances1[0]
    assert trader_balances0[1] < trader_balances1[1]

    # Wire up the new LM Callback reverting on any AMM interaction
    with boa.env.prank(admin):
        new_cb = LM_CALLBACK_WITH_REVERTS_DEPLOYER.deploy()
        controller.set_callback(new_cb)
        gauge_controller.add_gauge(new_cb.address, 0, 10**18)

    # Market reverts
    with boa.reverts():
        amm.exchange(1, 0, 10**20, 0, sender=trader)

    # Market reverts
    with boa.reverts():
        controller.borrow_more(10**17, 10**20, sender=borrower)

    borrower_balances2 = [
        borrowed_token.balanceOf(borrower),
        collateral_token.balanceOf(borrower),
    ]
    trader_balances2 = [borrowed_token.balanceOf(trader), collateral_token.balanceOf(trader)]

    assert borrower_balances2[0] == borrower_balances1[0]
    assert borrower_balances1[1] == borrower_balances2[1]
    assert trader_balances1[0] == trader_balances2[0]
    assert trader_balances1[1] == trader_balances2[1]
