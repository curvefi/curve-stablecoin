import boa
from tests.utils.deployers import LM_CALLBACK_WITH_REVERTS_DEPLOYER
from tests.utils.constants import ZERO_ADDRESS

WEEK = 7 * 86400


def test_add_new_lm_callback(
        accounts,
        admin,
        chad,
        collateral_token,
        stablecoin,
        market_controller,
        market_amm,
        gauge_controller,
):
    alice = accounts[0]

    # Remove current LM Callback
    market_controller.set_callback(ZERO_ADDRESS, sender=admin)

    boa.env.time_travel(seconds=2 * WEEK + 5)
    boa.deal(collateral_token, alice, 10**22)


    alice_balances0 = [stablecoin.balanceOf(alice), collateral_token.balanceOf(alice)]
    chad_balances0 = [stablecoin.balanceOf(chad), collateral_token.balanceOf(chad)]

    # Market interactions
    market_controller.create_loan(10**21, 10**21 * 2600, 10, sender=alice)
    market_amm.exchange(0, 1, 10**20, 0, sender=chad)

    alice_balances1 = [stablecoin.balanceOf(alice), collateral_token.balanceOf(alice)]
    chad_balances1 = [stablecoin.balanceOf(chad), collateral_token.balanceOf(chad)]

    assert alice_balances1[0] - alice_balances0[0] == 10**21 * 2600
    assert alice_balances0[1] - alice_balances1[1] == 10**21
    assert chad_balances0[0] > chad_balances1[0]
    assert chad_balances0[1] < chad_balances1[1]

    # Wire up the new LM Callback reverting on any AMM interaction
    with boa.env.prank(admin):
        new_cb = LM_CALLBACK_WITH_REVERTS_DEPLOYER.deploy()
        market_controller.set_callback(new_cb)
        gauge_controller.add_gauge(new_cb.address, 0, 10 ** 18)

    # Market interactions are still working
    market_amm.exchange(1, 0, 10**20, 0, sender=chad)
    market_controller.borrow_more(10**17, 10**20, sender=alice)

    alice_balances2 = [stablecoin.balanceOf(alice), collateral_token.balanceOf(alice)]
    chad_balances2 = [stablecoin.balanceOf(chad), collateral_token.balanceOf(chad)]

    assert alice_balances2[0] - alice_balances1[0] == 10 ** 20
    assert alice_balances1[1] - alice_balances2[1] == 10 ** 17
    assert chad_balances1[0] < chad_balances2[0]
    assert chad_balances1[1] > chad_balances2[1]
