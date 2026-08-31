"""
Repay paths the ported test suite never reaches.

test_repay.py and test_repay_full.py both run against a healthy, all-collateral
position and take every optional argument at its default. That leaves untested:

  * the collateral flush `_repay` performs before handing over to the controller
    (LeverageTransientZapLend.vy:406-410), whose stated purpose is to avoid a revert,
  * `_max_active_band` and `_shrink`, which the entry point exposes and forwards but
    which nothing ever passes a non-default value for,
  * a position in soft liquidation - where the controller refuses a callback repay
    outright unless `_shrink` is set, so the zap is only usable on such a position one
    particular way,
  * the `"Collateral must decrease"` guard, and
  * a full repay where the swap alone covers the debt and the caller's wallet
    contribution has to come back untouched.
"""

import boa
import pytest

from tests.utils import filter_logs
from tests.utils.constants import MAX_UINT256
from tests.utils.deployers import MALICIOUS_ROUTER_DEPLOYER

from tests.e2e.zaps.transient_leverage_zap.conftest import (
    approve_zap,
    borrowed_from_collateral,
    collateral_from_borrowed,
    make_deposit_calldata,
    make_repay_calldata,
)

N = 10


@pytest.fixture(scope="module")
def no_op_router(borrowed_token, collateral_token, leverage_zap, admin):
    """A whitelisted exchange that takes the call and does nothing at all."""
    router = MALICIOUS_ROUTER_DEPLOYER.deploy()
    boa.deal(borrowed_token, router.address, 10**9 * 10 ** borrowed_token.decimals())
    boa.deal(
        collateral_token, router.address, 10**9 * 10 ** collateral_token.decimals()
    )
    router.set_skip_swap(True)
    with boa.env.prank(admin):
        leverage_zap.set_exchange(router.address, True)
    return router


@pytest.fixture
def max_leverage_position(
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    A leveraged position taken out just under the maximum, so its bands sit right on
    top of the active band. The comfortable position `open_position` builds is ~90
    bands away from the active one and no realistic trade can reach it.
    """

    def _open():
        borrower = boa.env.generate_address()
        bd = borrowed_token.decimals()
        cd = collateral_token.decimals()

        user_collateral = 2 * 10**cd
        price = price_oracle.price()
        max_debt = leverage_zap.max_borrowable(controller, user_collateral, 0, N, price)
        leverage_collateral = collateral_from_borrowed(max_debt, price, bd, cd)
        max_debt = min(
            max_debt,
            controller.max_borrowable(user_collateral + leverage_collateral, N),
        )

        # A touch below the maximum, so the loan is comfortably creatable but still
        # sits at the top of the range
        d_debt = max_debt * 98 // 100
        collateral_out = collateral_from_borrowed(d_debt, price, bd, cd)
        calldata = make_deposit_calldata(
            controller_id,
            collateral_out * 999 // 1000,
            dummy_router,
            borrowed_token,
            collateral_token,
            d_debt,
            collateral_out,
        )

        boa.deal(collateral_token, borrower, 10**6 * 10**cd)
        boa.deal(borrowed_token, borrower, 10**6 * 10**bd)
        approve_zap(
            borrower, controller, leverage_zap, collateral_token, borrowed_token
        )
        with boa.env.prank(borrower):
            leverage_zap.create_loan(
                controller_id, user_collateral, d_debt, N, *calldata
            )
        return borrower

    return _open


@pytest.fixture
def soft_liquidate(amm, controller, collateral_token, borrowed_token):
    """
    Let an arbitrageur buy the top of the position out of the AMM, which is what puts a
    position into soft liquidation: part of it comes back as the borrowed token.
    """

    def _push(borrower):
        cd = collateral_token.decimals()
        ns = amm.read_user_tick_numbers(borrower)
        amount_out = (amm.bands_y(ns[0]) + amm.bands_y(ns[0] + 1) // 2) // 10 ** (
            18 - cd
        )
        amount_in = amm.get_dx(0, 1, amount_out)

        trader = boa.env.generate_address()
        boa.deal(borrowed_token, trader, amount_in + 1)
        with boa.env.prank(trader):
            borrowed_token.approve(amm.address, MAX_UINT256)
            amm.exchange_dy(0, 1, amount_out, amount_in + 1)

        assert controller.user_state(borrower)[1] > 0

    return _push


# ---------------------------------------------------------------------------
# Dust on the collateral side
# ---------------------------------------------------------------------------


def test_repay_collateral_dust_flushed_to_caller(
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
    The mirror of `test_repay_borrowed_dust_flushed_to_user`, and the case
    `_repay`'s own comment is about: the controller takes back whatever collateral the
    callback did not sell and refuses to take back more than it sent ("Collateral can't
    increase during repay", controller.vy:1004). Collateral already sitting in the zap
    would count towards that leftover, so it has to leave before the call.

    The dust here is larger than the amount being sold, which is exactly the case that
    would revert without the flush.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    borrowed_out = borrowed_from_collateral(
        collateral_to_swap, price_oracle.price(), bd, cd
    )
    dust = collateral_to_swap * 2

    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    boa.deal(collateral_token, leverage_zap.address, dust)
    collateral_before = collateral_token.balanceOf(borrower)

    with boa.env.prank(borrower):
        leverage_zap.repay(controller_id, 0, *calldata)
    logs = filter_logs(leverage_zap, "Repay", computation=leverage_zap._computation)

    # The dust went back to the caller and was not mistaken for position collateral
    assert collateral_token.balanceOf(borrower) == collateral_before + dust
    assert logs[0].state_collateral_used == collateral_to_swap
    assert logs[0].borrowed_from_state_collateral == borrowed_out

    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] - collateral_to_swap
    assert state1[2] == state0[2] - borrowed_out
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


# ---------------------------------------------------------------------------
# The forwarded controller arguments
# ---------------------------------------------------------------------------


def test_repay_max_active_band_too_low_reverts(
    open_position,
    controller,
    amm,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    `_max_active_band` is the caller's protection against being front-run into a worse
    band before their repay lands. The entry point takes it as a defaulted argument and
    forwards it, so a value the current band already exceeds has to be refused.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    borrowed_out = borrowed_from_collateral(
        collateral_to_swap, price_oracle.price(), bd, cd
    )
    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    too_low = amm.active_band() - 1
    with boa.env.prank(borrower):
        with boa.reverts():
            leverage_zap.repay(controller_id, 0, *calldata, too_low)

    assert controller.user_state(borrower) == state0

    # The same repay goes through once the bound admits the current band
    with boa.env.prank(borrower):
        leverage_zap.repay(controller_id, 0, *calldata, amm.active_band())

    assert controller.user_state(borrower)[0] == state0[0] - collateral_to_swap


def test_repay_soft_liquidated_position_requires_shrink(
    max_leverage_position,
    soft_liquidate,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    Once a position is in soft liquidation the controller refuses a callback repay
    unless `_shrink` is set (controller.vy:1040) - so on exactly the positions users
    most want to deleverage, the zap only works one way. Pinning both halves keeps that
    from silently becoming "the zap does not work here".
    """
    borrower = max_leverage_position()
    soft_liquidate(borrower)

    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    state0 = controller.user_state(borrower)
    assert state0[1] > 0  # part of the position is now the borrowed token

    collateral_to_swap = state0[0] // 4
    borrowed_out = borrowed_from_collateral(
        collateral_to_swap, price_oracle.price(), bd, cd
    )
    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        with boa.reverts():
            leverage_zap.repay(controller_id, 0, *calldata, 2**255 - 1, False)

    assert controller.user_state(borrower) == state0
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0

    with boa.env.prank(borrower):
        leverage_zap.repay(controller_id, 0, *calldata, 2**255 - 1, True)

    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] - collateral_to_swap
    # Shrinking also pays down the debt with the borrowed side of the position
    assert state1[2] == state0[2] - borrowed_out - state0[1]
    assert state1[1] == 0
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


def test_repay_soft_liquidated_reports_only_swap_proceeds(
    max_leverage_position,
    soft_liquidate,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    In soft liquidation the position holds borrowed tokens of its own, and the
    controller recovers those itself rather than routing them through the callback
    (controller.vy:1046). The zap must therefore still report - and be measured on -
    only what the exchange produced, with the position's own borrowed side neither
    double-counted in the event nor able to stand in for swap output.
    """
    borrower = max_leverage_position()
    soft_liquidate(borrower)

    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    state0 = controller.user_state(borrower)
    state_borrowed = state0[1]
    assert state_borrowed > 0

    collateral_to_swap = state0[0] // 4
    borrowed_out = borrowed_from_collateral(
        collateral_to_swap, price_oracle.price(), bd, cd
    )
    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    with boa.env.prank(borrower):
        leverage_zap.repay(controller_id, 0, *calldata, 2**255 - 1, True)
    logs = filter_logs(leverage_zap, "Repay", computation=leverage_zap._computation)

    assert len(logs) == 1
    assert logs[0].state_collateral_used == collateral_to_swap
    assert logs[0].borrowed_from_state_collateral == borrowed_out
    assert (
        controller.user_state(borrower)[2] == state0[2] - borrowed_out - state_borrowed
    )
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


# ---------------------------------------------------------------------------
# An exchange that sells nothing
# ---------------------------------------------------------------------------


def test_repay_without_selling_collateral_reverts(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    no_op_router,
    controller_id,
    price_oracle,
):
    """
    `callback_repay` insists the exchange actually consumed collateral. With
    `min_recv` at zero the slippage check cannot catch an exchange that did nothing, so
    "Collateral must decrease" is the only thing standing between the caller and a
    repay that hands their whole position back to the AMM having sold none of it.
    """
    borrower = open_position()
    state0 = controller.user_state(borrower)

    calldata = make_repay_calldata(
        controller_id,
        0,  # nothing expected back, so slippage cannot be what rejects this
        no_op_router,
        collateral_token,
        borrowed_token,
        state0[0] // 4,
        0,
    )

    with boa.env.prank(borrower):
        with boa.reverts("Collateral must decrease"):
            leverage_zap.repay(controller_id, 0, *calldata)

    assert controller.user_state(borrower) == state0
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


# ---------------------------------------------------------------------------
# Refunding the wallet contribution
# ---------------------------------------------------------------------------


def test_repay_full_refunds_unused_wallet_contribution(
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
    `_repay` pulls the wallet contribution up front, capped at the outstanding debt, so
    `max_value(uint256)` means "as much as needed". When the swap turns out to cover the
    whole debt on its own, none of it is needed - and all of it has to come back.

    test_repay_full.py only covers the opposite case, where the swap falls short and the
    wallet genuinely pays the difference.
    """
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0]
    borrowed_out = borrowed_from_collateral(
        collateral_to_swap, price_oracle.price(), bd, cd
    )
    assert borrowed_out > state0[2]  # the swap alone covers the debt

    calldata = make_repay_calldata(
        controller_id,
        borrowed_out * 999 // 1000,
        dummy_router,
        collateral_token,
        borrowed_token,
        collateral_to_swap,
        borrowed_out,
    )

    borrowed_before = borrowed_token.balanceOf(borrower)

    with boa.env.prank(borrower):
        leverage_zap.repay(controller_id, MAX_UINT256, *calldata)

    assert not controller.loan_exists(borrower)
    # The wallet was drawn on and made whole again, and keeps the surplus proceeds
    assert (
        borrowed_token.balanceOf(borrower) == borrowed_before + borrowed_out - state0[2]
    )
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
