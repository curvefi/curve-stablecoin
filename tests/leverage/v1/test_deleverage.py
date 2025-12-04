import pytest
from hypothesis import given
from hypothesis import strategies as st


@given(
    collateral_amt=st.floats(min_value=0.1, max_value=1000),
    repay_frac=st.floats(min_value=0.1, max_value=1),
)
@pytest.mark.parametrize(
    "collateral_token", ["sfrxETH", "wstETH", "WBTC", "WETH", "sfrxETH2", "tBTC"]
)
@pytest.mark.parametrize("route_idx", [0, 1, 2, 3, 4])
def test_deleverage(
    collaterals,
    controllers,
    llammas,
    leverage_zaps,
    deleverage_zaps,
    user,
    stablecoin_token,
    collateral_token,
    collateral_amt,
    repay_frac,
    route_idx,
):
    # 1. Create leveraged position

    N = 10
    decimals = collaterals[collateral_token].decimals()
    balance = (
        user.balance
        if collateral_token == "WETH"
        else collaterals[collateral_token].balanceOf(user)
    )
    _collateral_amt = min(int(collateral_amt * 10**decimals), balance)
    max_borrowable, _ = leverage_zaps[collateral_token].max_borrowable_and_collateral(
        _collateral_amt, N, route_idx
    )
    borrow_amt = int(max_borrowable * 0.3)
    _n1 = leverage_zaps[collateral_token].calculate_debt_n1(
        _collateral_amt, borrow_amt, N, route_idx
    )
    min_recv = int(
        leverage_zaps[collateral_token].get_collateral_underlying(borrow_amt, route_idx)
        * 0.999
    )

    value = _collateral_amt if collateral_token == "WETH" else 0
    controllers[collateral_token].create_loan_extended(
        _collateral_amt,
        borrow_amt,
        N,
        leverage_zaps[collateral_token].address,
        [route_idx, min_recv],
        value=value,
        sender=user,
    )

    # 2. Deleverage

    collateral_before, _, __, ___ = controllers[collateral_token].user_state(user)
    user_collateral_before = collaterals[collateral_token].balanceOf(user)

    repay_collateral_amount = min(
        int(collateral_before * repay_frac), collateral_before
    )
    repay_debt_amount = deleverage_zaps[collateral_token].get_stablecoins(
        repay_collateral_amount, route_idx
    )
    _n1 = 0
    if repay_debt_amount < borrow_amt:
        _n1 = deleverage_zaps[collateral_token].calculate_debt_n1(
            repay_collateral_amount, route_idx, user
        )

    controllers[collateral_token].repay_extended(
        deleverage_zaps[collateral_token].address,
        [route_idx, repay_collateral_amount, int(repay_debt_amount * 0.999)],
        sender=user,
    )

    collateral, stablecoin, debt, _N = controllers[collateral_token].user_state(user)
    n1, n2 = llammas[collateral_token].read_user_tick_numbers(user)

    assert stablecoin == 0

    if repay_debt_amount < borrow_amt:
        assert collateral == collateral_before - repay_collateral_amount
        assert abs((borrow_amt - debt) - repay_debt_amount) / repay_debt_amount < 1e-4
        assert n1 == _n1
        assert n2 == _n1 + _N - 1
    else:
        assert collateral == 0
        assert debt == 0
        assert (
            abs((repay_debt_amount - borrow_amt) - stablecoin_token.balanceOf(user))
            / stablecoin_token.balanceOf(user)
            < 1e-4
        )
        assert (
            collaterals[collateral_token].balanceOf(user) - user_collateral_before
            == collateral_before - repay_collateral_amount
        )


@given(
    collateral_amt=st.floats(min_value=0.1, max_value=1000),
    repay_frac=st.floats(min_value=0.1, max_value=1),
)
# sfrxETH is in sunset mode, can't borrow max
@pytest.mark.parametrize(
    "collateral_token", ["wstETH", "WBTC", "WETH", "sfrxETH2", "tBTC"]
)
@pytest.mark.parametrize("route_idx", [0, 1, 2, 3, 4])
def test_deleverage_underwater(
    collaterals,
    controllers,
    llammas,
    leverage_zaps,
    deleverage_zaps,
    user,
    trader,
    stablecoin_token,
    collateral_token,
    collateral_amt,
    repay_frac,
    route_idx,
):
    # 1. Create leveraged position

    N = 10
    decimals = collaterals[collateral_token].decimals()
    balance = (
        user.balance
        if collateral_token == "WETH"
        else collaterals[collateral_token].balanceOf(user)
    )
    _collateral_amt = min(int(collateral_amt * 10**decimals), balance)
    max_borrowable, _ = leverage_zaps[collateral_token].max_borrowable_and_collateral(
        _collateral_amt, N, route_idx
    )
    borrow_amt = max_borrowable
    _n1 = leverage_zaps[collateral_token].calculate_debt_n1(
        _collateral_amt, borrow_amt, N, route_idx
    )
    min_recv = int(
        leverage_zaps[collateral_token].get_collateral_underlying(borrow_amt, route_idx)
        * 0.999
    )

    value = _collateral_amt if collateral_token == "WETH" else 0
    controllers[collateral_token].create_loan_extended(
        _collateral_amt,
        borrow_amt,
        N,
        leverage_zaps[collateral_token].address,
        [route_idx, min_recv],
        value=value,
        sender=user,
    )

    # 2. Trade to push user to soft-liquidation

    n1, n2 = llammas[collateral_token].read_user_tick_numbers(user)
    active_band = llammas[collateral_token].active_band()
    total_collateral_to_trade = 0
    for i in range(active_band, n1 + 2):
        if i == n1 + 2:
            total_collateral_to_trade += llammas[collateral_token].bands_y(i) // 2
        else:
            total_collateral_to_trade += llammas[collateral_token].bands_y(i)
    total_collateral_to_trade = total_collateral_to_trade * 10**decimals // 10**18

    llammas[collateral_token].exchange_dy(
        0, 1, total_collateral_to_trade, 10**26, sender=trader
    )

    active_band = llammas[collateral_token].active_band()
    collateral_before, stablecoin_before, debt_before, _N = controllers[
        collateral_token
    ].user_state(user)

    assert active_band > n1
    assert active_band < n2
    assert stablecoin_before > 0

    # 2. Deleverage

    user_collateral_before = collaterals[collateral_token].balanceOf(user)
    repay_collateral_amount = int(collateral_before * repay_frac)
    repay_debt_amount = deleverage_zaps[collateral_token].get_stablecoins(
        repay_collateral_amount, route_idx
    )

    if repay_debt_amount + stablecoin_before > debt_before:  # Full repayment
        controllers[collateral_token].repay_extended(
            deleverage_zaps[collateral_token].address,
            [route_idx, repay_collateral_amount, int(repay_debt_amount * 0.999)],
            sender=user,
        )

        collateral, stablecoin, debt, _N = controllers[collateral_token].user_state(
            user
        )
        assert collateral == 0
        assert debt == 0
        assert (
            abs(
                (repay_debt_amount + stablecoin_before - borrow_amt)
                - stablecoin_token.balanceOf(user)
            )
            / stablecoin_token.balanceOf(user)
            < 3e-4
        )
        assert (
            collaterals[collateral_token].balanceOf(user) - user_collateral_before
            == collateral_before - repay_collateral_amount
        )
    # else:  # Partial repayment reverts
    #     with ape.reverts(""):
    #         controllers[collateral_token].repay_extended(
    #             deleverage_zaps[collateral_token].address,
    #             [route_idx, repay_collateral_amount, int(repay_debt_amount * 0.999)],
    #             sender=user,
    #         )
