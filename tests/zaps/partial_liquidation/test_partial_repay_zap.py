import boa
import pytest

from eth_abi import encode
from eth_utils import function_signature_to_4byte_selector

from tests.utils.constants import MAX_UINT256


def _make_exchange_calldata(collateral_token, borrowed_token, borrowed_from_sender):
    return function_signature_to_4byte_selector(
        "callback_liquidate_partial(address,address,uint256)"
    ) + encode(
        ["address", "address", "uint256"],
        [collateral_token.address, borrowed_token.address, borrowed_from_sender],
    )


def _get_zap_indices(market_type, mint_factory, factory, controller):
    controller_address = str(controller.address).lower()
    if market_type == "mint":
        for i in range(mint_factory.n_collaterals()):
            if str(mint_factory.controllers(i)).lower() == controller_address:
                return i
    else:
        for i in range(factory.market_count()):
            market = factory.markets(i)
            market_controller = (
                market.controller if hasattr(market, "controller") else market[1]
            )
            market_controller_address = (
                market_controller.address
                if hasattr(market_controller, "address")
                else market_controller
            )
            if str(market_controller_address).lower() == controller_address:
                return i
    raise ValueError("Controller index not found in selected factory")


@pytest.mark.parametrize("is_approved", [True, False])
def test_users_to_liquidate_callback(
    controller_for_liquidation,
    partial_repay_zap,
    market_type,
    mint_factory,
    factory,
    is_approved,
):
    user = boa.env.generate_address("user")
    controller = controller_for_liquidation(sleep_time=int(31.3 * 86400), user=user)
    c_idx = _get_zap_indices(market_type, mint_factory, factory, controller)

    if is_approved:
        controller.approve(partial_repay_zap.address, True, sender=user)

    users_to_liquidate = partial_repay_zap.users_to_liquidate(c_idx)

    if not is_approved:
        assert users_to_liquidate == []
    else:
        assert len(users_to_liquidate) == 1
        assert users_to_liquidate[0][0] == user


def test_liquidate_partial(
    borrowed_token,
    controller_for_liquidation,
    partial_repay_zap,
    market_type,
    mint_factory,
    factory,
):
    user = boa.env.generate_address("user")
    liquidator = boa.env.generate_address("liquidator")
    controller = controller_for_liquidation(sleep_time=int(29.0 * 86400), user=user)
    c_idx = _get_zap_indices(market_type, mint_factory, factory, controller)
    someone_else = str(partial_repay_zap.address)
    controller.approve(someone_else, True, sender=user)

    h = controller.health(user) / 10**16
    assert 0.9 < h < 1

    # Ensure liquidator has stablecoin
    boa.deal(borrowed_token, liquidator, 1000 * 10 ** borrowed_token.decimals())
    with boa.env.prank(liquidator):
        borrowed_token.approve(partial_repay_zap.address, 2**256 - 1)
        partial_repay_zap.liquidate_partial(c_idx, user, 0)

    h = controller.health(user) / 10**16
    assert h > 1


def test_liquidate_partial_callback(
    borrowed_token,
    collateral_token,
    controller_for_liquidation,
    partial_repay_zap,
    partial_repay_zap_tester,
    market_type,
    mint_factory,
    factory,
):
    user = boa.env.generate_address("user")
    liquidator = boa.env.generate_address("liquidator")
    controller = controller_for_liquidation(sleep_time=int(29.0 * 86400), user=user)
    c_idx = _get_zap_indices(market_type, mint_factory, factory, controller)
    controller.approve(partial_repay_zap.address, True, sender=user)
    borrowed_from_sender = partial_repay_zap.users_to_liquidate(c_idx)[0].dx
    calldata = _make_exchange_calldata(
        collateral_token, borrowed_token, borrowed_from_sender
    )

    initial_health = controller.health(user)

    initial_collateral = collateral_token.balanceOf(partial_repay_zap_tester.address)
    # Ensure partial_repay_zap_tester has stablecoin
    boa.deal(
        borrowed_token, partial_repay_zap_tester, 1000 * 10 ** borrowed_token.decimals()
    )
    with boa.env.prank(liquidator):
        borrowed_token.approve(partial_repay_zap.address, 2**256 - 1)
        partial_repay_zap.liquidate_partial(
            c_idx, user, 0, partial_repay_zap_tester.address, calldata
        )

    final_health = controller.health(user)
    assert final_health > initial_health

    final_collateral = collateral_token.balanceOf(partial_repay_zap_tester.address)
    assert final_collateral > initial_collateral

    assert borrowed_token.balanceOf(partial_repay_zap.address) == 0
    assert collateral_token.balanceOf(partial_repay_zap.address) == 0


@pytest.mark.parametrize("use_callback", [True, False])
def test_liquidate_partial_uses_exact_amount(
    borrowed_token,
    collateral_token,
    controller_for_liquidation,
    partial_repay_zap,
    partial_repay_zap_tester,
    market_type,
    mint_factory,
    factory,
    use_callback,
):
    user = boa.env.generate_address("user")
    liquidator = boa.env.generate_address("liquidator")
    controller = controller_for_liquidation(sleep_time=int(29.0 * 86400), user=user)
    c_idx = _get_zap_indices(market_type, mint_factory, factory, controller)
    controller.approve(partial_repay_zap.address, True, sender=user)

    position = partial_repay_zap.users_to_liquidate(c_idx)[0]
    borrowed_from_sender = position.dx

    if use_callback:
        calldata = _make_exchange_calldata(
            collateral_token,
            borrowed_token,
            borrowed_from_sender,
        )
        boa.deal(
            borrowed_token,
            partial_repay_zap_tester,
            1000 * 10 ** borrowed_token.decimals(),
        )
        pre_balance = borrowed_token.balanceOf(partial_repay_zap_tester)

        with boa.env.prank(liquidator):
            borrowed_token.approve(partial_repay_zap.address, 2**256 - 1)
            partial_repay_zap.liquidate_partial(
                c_idx, user, 0, partial_repay_zap_tester.address, calldata
            )

        post_balance = borrowed_token.balanceOf(partial_repay_zap_tester)

    else:
        # get money to liquidate: in real scenario this would be a separate address
        boa.deal(borrowed_token, liquidator, 1000 * 10 ** borrowed_token.decimals())
        pre_balance = borrowed_token.balanceOf(liquidator)
        with boa.env.prank(liquidator):
            borrowed_token.approve(partial_repay_zap.address, MAX_UINT256)
            partial_repay_zap.liquidate_partial(c_idx, user, 0)
        post_balance = borrowed_token.balanceOf(liquidator)

    spent = pre_balance - post_balance
    assert spent == borrowed_from_sender
