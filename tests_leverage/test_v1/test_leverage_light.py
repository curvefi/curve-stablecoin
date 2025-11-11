import pytest


@pytest.mark.parametrize("collateral_token", ["sfrxETH", "wstETH", "WBTC", "WETH", "sfrxETH2", "tBTC"])
@pytest.mark.parametrize("borrow_amt", [10_000 * 10**18, 2**256 - 1])
@pytest.mark.parametrize("route_idx", [0, 1, 2, 3, 4])
def test_leverage(collaterals, controllers, llammas, leverage_zaps, user, collateral_token, borrow_amt, route_idx):
    collateral_amt = 1
    N = 10
    decimals = collaterals[collateral_token].decimals()
    balance = user.balance if collateral_token == "WETH" else collaterals[collateral_token].balanceOf(user)
    _collateral_amt = min(int(collateral_amt * 10**decimals), balance)
    max_borrowable, max_collateral = leverage_zaps[collateral_token].max_borrowable_and_collateral(_collateral_amt, N, route_idx)
    assert max_borrowable > 0
    _borrow_amt = min(max_borrowable, borrow_amt)
    if _borrow_amt == max_borrowable:
        expected_collateral = max_collateral
    else:
        expected_collateral = _collateral_amt + leverage_zaps[collateral_token].get_collateral(_borrow_amt, route_idx)
    _n1 = leverage_zaps[collateral_token].calculate_debt_n1(_collateral_amt, _borrow_amt, N, route_idx)
    min_recv = int(leverage_zaps[collateral_token].get_collateral_underlying(_borrow_amt, route_idx) * 0.999)

    value = _collateral_amt if collateral_token == "WETH" else 0
    controllers[collateral_token].create_loan_extended(
        _collateral_amt,
        _borrow_amt,
        N,
        leverage_zaps[collateral_token].address,
        [route_idx, min_recv],
        value=value,
        sender=user,
    )

    collateral, stablecoin, debt, _N = controllers[collateral_token].user_state(user)
    n1, n2 = llammas[collateral_token].read_user_tick_numbers(user)

    assert abs((expected_collateral - collateral) / collateral) < 2e-7
    assert stablecoin == 0
    assert debt == _borrow_amt
    assert N == _N
    assert n1 == _n1
    assert n2 == _n1 + N - 1
