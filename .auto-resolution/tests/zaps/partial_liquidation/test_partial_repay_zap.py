import boa
import pytest


@pytest.mark.parametrize("is_approved", [True, False])
def test_users_to_liquidate(
    controller_for_liquidation,
    accounts,
    partial_repay_zap,
    is_approved,
):
    user = accounts[1]
    controller = controller_for_liquidation(sleep_time=int(33 * 86400), user=user)

    if is_approved:
        someone_else = str(partial_repay_zap.address)
        controller.approve(someone_else, True, sender=user)

    users_to_liquidate = partial_repay_zap.users_to_liquidate(controller.address)

    if not is_approved:
        assert users_to_liquidate == []
    else:
        assert len(users_to_liquidate) == 1
        assert users_to_liquidate[0][0] == user


def test_liquidate_partial(
    borrowed_token,
    controller_for_liquidation,
    accounts,
    partial_repay_zap,
):
    user = accounts[1]
    liquidator = accounts[2]
    controller = controller_for_liquidation(sleep_time=int(30.7 * 86400), user=user)
    someone_else = str(partial_repay_zap.address)
    controller.approve(someone_else, True, sender=user)

    h = controller.health(user) / 10**16
    assert 0.9 < h < 1

    # Ensure liquidator has stablecoin
    boa.deal(borrowed_token, liquidator, 10**21)
    with boa.env.prank(liquidator):
        borrowed_token.approve(partial_repay_zap.address, 2**256 - 1)
        partial_repay_zap.liquidate_partial(controller.address, user, 0)

    h = controller.health(user) / 10**16
    assert h > 1
