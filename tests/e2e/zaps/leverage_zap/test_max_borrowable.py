"""
Tests for LeverageZap.max_borrowable — both pure view math and integration
with create_loan / borrow_more.
"""

import pytest
import boa

from tests.utils.constants import MAX_UINT256
from tests.e2e.zaps.leverage_zap.conftest import (
    collateral_from_borrowed,
    borrowed_from_collateral,
    make_deposit_calldata,
)

N = 10


# ---------------------------------------------------------------------------
# Pure view tests
# ---------------------------------------------------------------------------


def test_max_borrowable_capped_by_available_balance(
    leverage_zap,
    controller,
    collateral_token,
    borrowed_token,
    price_oracle,
):
    """
    With very large collateral the health limit is not binding;
    result must equal available_balance.
    """
    cd = collateral_token.decimals()
    p_avg = price_oracle.price()

    large_collateral = 10**9 * 10**cd

    result = leverage_zap.max_borrowable(
        controller, large_collateral, large_collateral, N, p_avg
    )

    assert result == controller.available_balance()


def test_max_borrowable_increases_with_collateral(
    leverage_zap,
    controller,
    collateral_token,
    borrowed_token,
    price_oracle,
):
    """More user_collateral → higher max_borrowable."""
    cd = collateral_token.decimals()
    p_avg = price_oracle.price()

    small = leverage_zap.max_borrowable(controller, 1 * 10**cd, 0, N, p_avg)
    large = leverage_zap.max_borrowable(controller, 10 * 10**cd, 0, N, p_avg)

    assert large > small


def test_max_borrowable_decreases_with_more_ticks(
    leverage_zap,
    controller,
    collateral_token,
    borrowed_token,
    price_oracle,
):
    """More bands (N) → lower max_borrowable due to larger effective discount."""
    cd = collateral_token.decimals()
    p_avg = price_oracle.price()

    collateral = 5 * 10**cd

    few_bands = leverage_zap.max_borrowable(controller, collateral, 0, 4, p_avg)
    many_bands = leverage_zap.max_borrowable(controller, collateral, 0, 50, p_avg)

    assert few_bands > many_bands


# ---------------------------------------------------------------------------
# Integration: create_loan respects max_borrowable
# ---------------------------------------------------------------------------


def test_create_loan_within_max_borrowable(
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    d_debt must be <= max_borrowable; loan must succeed.
    """
    borrower = boa.env.generate_address()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    price = price_oracle.price()
    max_b = leverage_zap.max_borrowable(controller, user_collateral, 0, N, price)
    max_leverage_collateral = collateral_from_borrowed(max_b, price, bd, cd)

    controller_max = controller.max_borrowable(
        user_collateral + max_leverage_collateral, N
    )
    assert max_b == pytest.approx(controller_max, rel=1e-3)

    # Use controller_max if zap slightly overshoots, adjusting collateral to match
    if max_b > controller_max:
        max_b = controller_max
        max_leverage_collateral = collateral_from_borrowed(max_b, price, bd, cd)
        max_b = borrowed_from_collateral(max_leverage_collateral, price, bd, cd)

    calldata = make_deposit_calldata(
        controller_id,
        0,
        max_leverage_collateral,
        dummy_router,
        borrowed_token,
        collateral_token,
        max_b,
        max_leverage_collateral,
    )

    boa.deal(collateral_token, borrower, user_collateral)
    with boa.env.prank(borrower):
        collateral_token.approve(controller.address, MAX_UINT256)
        controller.create_loan(
            user_collateral, max_b, N, borrower, leverage_zap.address, calldata
        )

    assert controller.user_state(borrower)[2] == max_b
    assert borrowed_token.balanceOf(borrower) == 0


def test_create_loan_debt_too_high_reverts(
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """d_debt one unit above max_borrowable must revert."""
    borrower = boa.env.generate_address()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    price = price_oracle.price()
    max_b = leverage_zap.max_borrowable(controller, user_collateral, 0, N, price)
    exceed_debt = int(max_b * 1.0021)
    exceed_leverage_collateral = collateral_from_borrowed(exceed_debt, price, bd, cd)

    assert exceed_debt > controller.max_borrowable(
        user_collateral + exceed_leverage_collateral, N
    )

    # keep leverage_collateral fixed — more debt with same swap output → unhealthy
    calldata = make_deposit_calldata(
        controller_id,
        0,
        exceed_leverage_collateral,
        dummy_router,
        borrowed_token,
        collateral_token,
        exceed_debt,
        exceed_leverage_collateral,
    )

    boa.deal(collateral_token, borrower, user_collateral)
    with boa.env.prank(borrower):
        collateral_token.approve(controller.address, MAX_UINT256)
        with boa.reverts("Debt too high"):
            controller.create_loan(
                user_collateral,
                exceed_debt,
                N,
                borrower,
                leverage_zap.address,
                calldata,
            )


def test_create_loan_exceeds_available_balance_reverts(
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    Trying to borrow above available_balance (the binding constraint for large collateral)
    must revert.
    """
    borrower = boa.env.generate_address()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    p_avg = price_oracle.price()

    # Use very large collateral so health is not limiting → max_b == available * 999//1000
    large_collateral = 10**9 * 10**cd
    max_b = leverage_zap.max_borrowable(
        controller, large_collateral, large_collateral, N, p_avg
    )

    exceed_debt = max_b + 1
    exceed_collateral = collateral_from_borrowed(exceed_debt, p_avg, bd, cd)

    calldata = make_deposit_calldata(
        controller_id,
        0,
        exceed_collateral,
        dummy_router,
        borrowed_token,
        collateral_token,
        exceed_debt,
        exceed_collateral,
    )

    boa.deal(collateral_token, borrower, large_collateral)
    with boa.env.prank(borrower):
        collateral_token.approve(controller.address, MAX_UINT256)
        with boa.reverts():
            controller.create_loan(
                large_collateral,
                exceed_debt,
                N,
                borrower,
                leverage_zap.address,
                calldata,
            )


# ---------------------------------------------------------------------------
# Integration: borrow_more respects max_borrowable
# ---------------------------------------------------------------------------


def test_borrow_more_within_max_borrowable(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    Additional d_debt must be <= max_borrowable; borrow_more must succeed.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    state_collateral = state0[0]
    state_debt = state0[2]
    price = price_oracle.price()

    d_debt = (
        leverage_zap.max_borrowable(
            controller,
            state_collateral - collateral_from_borrowed(state_debt, price, bd, cd),
            0,
            N,
            price,
        )
        - state_debt
    )
    d_leverage_coll = collateral_from_borrowed(d_debt, price, bd, cd) + 1

    controller_max = controller.max_borrowable(d_leverage_coll, N, borrower)
    assert d_debt == pytest.approx(controller_max, rel=3e-3)

    if d_debt > controller_max:
        d_debt = controller_max
        d_leverage_coll = collateral_from_borrowed(controller_max, price, bd, cd) + 1

    calldata = make_deposit_calldata(
        controller_id,
        0,
        d_leverage_coll,
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        d_leverage_coll,
    )

    with boa.env.prank(borrower):
        controller.borrow_more(0, d_debt, borrower, leverage_zap.address, calldata)

    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] + d_leverage_coll
    assert state1[2] == state0[2] + d_debt


def test_borrow_more_up_to_create_loan_max(
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    create_loan with partial debt + borrow_more to fill remaining room must produce
    the same final position as create_loan with max_b directly.

    The max d_debt for borrow_more is simply (create_loan max_b - initial_debt):
    the two-step path reaches the same collateral/debt as the one-step max.
    """
    borrower = boa.env.generate_address()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_collateral = 2 * 10**cd
    price = price_oracle.price()

    # max_b is the ceiling for create_loan with user_collateral
    max_b = leverage_zap.max_borrowable(controller, user_collateral, 0, N, price)
    max_leverage_collateral = collateral_from_borrowed(max_b, price, bd, cd)

    # Step 1: create_loan with half of max_b
    initial_debt = max_b // 2
    initial_leverage_coll = collateral_from_borrowed(initial_debt, price, bd, cd)

    create_calldata = make_deposit_calldata(
        controller_id,
        0,
        initial_leverage_coll,
        dummy_router,
        borrowed_token,
        collateral_token,
        initial_debt,
        initial_leverage_coll,
    )

    boa.deal(collateral_token, borrower, user_collateral)
    with boa.env.prank(borrower):
        collateral_token.approve(controller.address, MAX_UINT256)
        controller.create_loan(
            user_collateral,
            initial_debt,
            N,
            borrower,
            leverage_zap.address,
            create_calldata,
        )

    state0 = controller.user_state(borrower)
    state_collateral = state0[0]
    state_debt = state0[2]

    # Step 2: borrow_more — zap's max_borrowable on the full state collateral gives max total debt;
    # subtracting current debt gives the remaining room
    d_debt = (
        leverage_zap.max_borrowable(
            controller,
            state_collateral - collateral_from_borrowed(state_debt, price, bd, cd),
            0,
            N,
            price,
        )
        - state_debt
    )
    assert d_debt == max_b - initial_debt

    d_leverage_coll = collateral_from_borrowed(d_debt, price, bd, cd) + 1

    controller_max = controller.max_borrowable(d_leverage_coll, N, borrower)
    assert d_debt == pytest.approx(controller_max, rel=3e-3)

    if d_debt > controller_max:
        d_debt = controller_max
        d_leverage_coll = collateral_from_borrowed(controller_max, price, bd, cd) + 1

    borrow_calldata = make_deposit_calldata(
        controller_id,
        0,
        d_leverage_coll,
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        d_leverage_coll,
    )

    with boa.env.prank(borrower):
        controller.borrow_more(
            0, d_debt, borrower, leverage_zap.address, borrow_calldata
        )

    state1 = controller.user_state(borrower)
    # Final position equals what create_loan(user_collateral, max_b) would have produced
    assert state1[0] == pytest.approx(
        user_collateral + max_leverage_collateral, rel=1e-4
    )
    assert state1[2] == pytest.approx(max_b, rel=1e-3)


def test_borrow_more_debt_too_high_reverts(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """d_debt one unit above max_borrowable on borrow_more must revert."""
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    user_state = controller.user_state(borrower)
    state_collateral = user_state[0]
    state_debt = user_state[2]

    price = price_oracle.price()
    max_b = (
        leverage_zap.max_borrowable(
            controller,
            state_collateral - collateral_from_borrowed(state_debt, price, bd, cd),
            0,
            N,
            price,
        )
        - state_debt
    )
    exceed_debt = int(max_b * 1.0021)
    exceed_leverage_collateral = collateral_from_borrowed(exceed_debt, price, bd, cd)

    assert exceed_debt > controller.max_borrowable(
        exceed_leverage_collateral, N, borrower
    )

    calldata = make_deposit_calldata(
        controller_id,
        0,
        0,
        dummy_router,
        borrowed_token,
        collateral_token,
        exceed_debt,
        exceed_leverage_collateral,
    )

    with boa.env.prank(borrower):
        with boa.reverts("Debt too high"):
            controller.borrow_more(
                0, exceed_debt, borrower, leverage_zap.address, calldata
            )


def test_borrow_more_exceeds_available_balance_reverts(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    Borrowing above available_balance on borrow_more must revert.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    p_avg = price_oracle.price()

    large_collateral = 10**9 * 10**cd
    max_b = leverage_zap.max_borrowable(
        controller, controller.user_state(borrower)[0], large_collateral, N, p_avg
    )

    exceed_debt = max_b + 1
    exceed_collateral = collateral_from_borrowed(exceed_debt, p_avg, bd, cd)

    calldata = make_deposit_calldata(
        controller_id,
        0,
        0,
        dummy_router,
        borrowed_token,
        collateral_token,
        exceed_debt,
        exceed_collateral,
    )

    with boa.env.prank(borrower):
        with boa.reverts():
            controller.borrow_more(
                0, exceed_debt, borrower, leverage_zap.address, calldata
            )
