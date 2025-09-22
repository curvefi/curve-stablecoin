import boa
import pytest

from eth_utils import to_bytes


@pytest.mark.parametrize("is_approved", [True, False])
def test_users_to_liquidate_callback(
    controller_for_liquidation,
    accounts,
    partial_repay_zap_callback,
    is_approved,
):
    user = accounts[1]
    controller = controller_for_liquidation(sleep_time=int(33 * 86400), user=user)

    if is_approved:
        callbacker = str(partial_repay_zap_callback.address)
        controller.approve(callbacker, True, sender=user)

    users_to_liquidate = partial_repay_zap_callback.users_to_liquidate(
        controller.address
    )

    if not is_approved:
        assert users_to_liquidate == []
    else:
        assert len(users_to_liquidate) == 1
        assert users_to_liquidate[0][0] == user


def test_liquidate_partial(
    borrowed_token,
    controller_for_liquidation,
    accounts,
    partial_repay_zap_callback,
):
    user = accounts[1]
    liquidator = accounts[2]
    controller = controller_for_liquidation(sleep_time=int(30.7 * 86400), user=user)
    someone_else = str(partial_repay_zap_callback.address)
    controller.approve(someone_else, True, sender=user)

    h = controller.health(user) / 10**16
    assert 0.9 < h < 1

    # Ensure liquidator has stablecoin
    boa.deal(borrowed_token, liquidator, 10**21)
    with boa.env.prank(liquidator):
        borrowed_token.approve(partial_repay_zap_callback.address, 2**256 - 1)
        partial_repay_zap_callback.liquidate_partial(controller.address, user, 0)

    h = controller.health(user) / 10**16
    assert h > 1


def test_liquidate_partial_callback(
    borrowed_token,
    collateral_token,
    controller_for_liquidation,
    accounts,
    partial_repay_zap_callback,
    partial_repay_zap_tester,
):
    calldata = to_bytes(hexstr=borrowed_token.address)

    user = accounts[1]
    liquidator = accounts[2]
    controller = controller_for_liquidation(sleep_time=int(30.7 * 86400), user=user)
    callbacker = str(partial_repay_zap_callback.address)
    controller.approve(callbacker, True, sender=user)

    initial_health = controller.health(user)

    boa.deal(borrowed_token, liquidator, 10**21)
    initial_collateral = collateral_token.balanceOf(partial_repay_zap_tester.address)

    # Ensure partial_repay_zap_tester has stablecoin
    boa.deal(borrowed_token, partial_repay_zap_tester, 10**21)
    with boa.env.prank(liquidator):
        borrowed_token.approve(partial_repay_zap_callback.address, 2**256 - 1)
        partial_repay_zap_callback.liquidate_partial(
            controller.address, user, 0, partial_repay_zap_tester.address, calldata
        )

    final_health = controller.health(user)
    assert final_health > initial_health

    final_collateral = collateral_token.balanceOf(partial_repay_zap_tester.address)
    assert final_collateral > initial_collateral

    assert borrowed_token.balanceOf(partial_repay_zap_callback.address) == 0
    assert collateral_token.balanceOf(partial_repay_zap_callback.address) == 0
