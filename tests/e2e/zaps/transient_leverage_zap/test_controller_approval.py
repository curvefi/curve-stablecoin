"""
Tests for the trust assumption TransientLeverageZap introduces: the zap is the entry
point and acts *for* the caller, so the caller must grant it `controller.approve(zap,
True)`. The older LeverageZap needed no such approval - the user called the controller
themselves and the zap was only a callback.

Two things need pinning:

  * the approval is genuinely required (an otherwise identical call fails without it,
    and succeeds once it is granted), and
  * the approval only ever benefits the account that granted it. The zap holds standing
    controller approvals and standing ERC20 approvals from many users at once, and
    every entry point derives the position it touches from `msg.sender`, never from an
    argument - so one user's approval must not let anyone else move their funds.
"""

import boa
import pytest

from tests.utils.constants import MAX_UINT256

from tests.e2e.zaps.transient_leverage_zap.conftest import (
    approve_zap,
    borrowed_from_collateral,
    collateral_from_borrowed,
    make_deposit_calldata,
    make_repay_calldata,
)

N = 10


def approve_tokens_only(user, leverage_zap, collateral_token, borrowed_token):
    """Everything `approve_zap` does except the controller approval."""
    with boa.env.prank(user):
        collateral_token.approve(leverage_zap.address, MAX_UINT256)
        borrowed_token.approve(leverage_zap.address, MAX_UINT256)


@pytest.fixture
def funded_user(collateral_token, borrowed_token):
    def _fund():
        user = boa.env.generate_address()
        boa.deal(collateral_token, user, 10**6 * 10 ** collateral_token.decimals())
        boa.deal(borrowed_token, user, 10**6 * 10 ** borrowed_token.decimals())
        return user

    return _fund


# ---------------------------------------------------------------------------
# The approval is required
# ---------------------------------------------------------------------------


def test_create_loan_requires_controller_approval(
    funded_user,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    Token approvals alone are not enough: without `controller.approve(zap, True)` the
    controller rejects the zap acting for the user. Granting it makes the identical
    call go through, so the approval - and nothing else - is what was missing.
    """
    user = funded_user()
    approve_tokens_only(user, leverage_zap, collateral_token, borrowed_token)

    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    collateral_out = collateral_from_borrowed(d_debt, price_oracle.price(), bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
        collateral_out * 999 // 1000,
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        collateral_out,
    )

    assert controller.approval(user, leverage_zap.address) is False
    collateral_before = collateral_token.balanceOf(user)

    with boa.env.prank(user):
        with boa.reverts():
            leverage_zap.create_loan(
                controller_id, user_collateral, d_debt, N, *calldata
            )

    # Nothing moved and no position was opened
    assert not controller.loan_exists(user)
    assert collateral_token.balanceOf(user) == collateral_before
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0

    # The same call succeeds once the controller approval is in place
    with boa.env.prank(user):
        controller.approve(leverage_zap.address, True)
        leverage_zap.create_loan(controller_id, user_collateral, d_debt, N, *calldata)

    assert controller.loan_exists(user)
    assert controller.user_state(user)[0] == user_collateral + collateral_out


def test_borrow_more_requires_controller_approval(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """Revoking the approval on an existing position blocks further leverage."""
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    d_debt = 1000 * 10**bd
    collateral_out = collateral_from_borrowed(d_debt, price_oracle.price(), bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
        collateral_out * 999 // 1000,
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        collateral_out,
    )

    with boa.env.prank(borrower):
        controller.approve(leverage_zap.address, False)

    state0 = controller.user_state(borrower)
    with boa.env.prank(borrower):
        with boa.reverts():
            leverage_zap.borrow_more(controller_id, 0, d_debt, *calldata)

    assert controller.user_state(borrower) == state0
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0

    with boa.env.prank(borrower):
        controller.approve(leverage_zap.address, True)
        leverage_zap.borrow_more(controller_id, 0, d_debt, *calldata)

    assert controller.user_state(borrower)[0] == state0[0] + collateral_out


def test_repay_requires_controller_approval(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """Revoking the approval blocks deleveraging too, and strands nothing in the zap."""
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

    with boa.env.prank(borrower):
        controller.approve(leverage_zap.address, False)

    borrowed_before = borrowed_token.balanceOf(borrower)
    with boa.env.prank(borrower):
        with boa.reverts():
            leverage_zap.repay(controller_id, 0, *calldata)

    # The zap pulls the wallet contribution up front - a rejected repay must not
    # keep it, and the revert must roll the whole thing back
    assert controller.user_state(borrower) == state0
    assert borrowed_token.balanceOf(borrower) == borrowed_before
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0

    with boa.env.prank(borrower):
        controller.approve(leverage_zap.address, True)
        leverage_zap.repay(controller_id, 0, *calldata)

    assert controller.user_state(borrower)[0] == state0[0] - collateral_to_swap


# ---------------------------------------------------------------------------
# The approval benefits only the account that granted it
# ---------------------------------------------------------------------------


def test_zap_cannot_repay_another_users_position(
    open_position,
    funded_user,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    user2 has approved the zap on the controller and for both tokens. user2 calls the
    repay entry point with calldata sized for user2's position: the zap must act for
    user2 (who has no loan), never for user2.
    """
    user1 = open_position()
    user2 = funded_user()
    approve_zap(user2, controller, leverage_zap, collateral_token, borrowed_token)

    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    user1_state = controller.user_state(user1)
    user1_collateral = collateral_token.balanceOf(user1)
    user1_borrowed = borrowed_token.balanceOf(user1)

    collateral_to_swap = user1_state[0] // 4
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

    with boa.env.prank(user2):
        # user2 has no loan, so there is nothing for the zap to repay on his behalf
        with boa.reverts():
            leverage_zap.repay(controller_id, MAX_UINT256, *calldata)

    assert controller.user_state(user1) == user1_state
    assert collateral_token.balanceOf(user1) == user1_collateral
    assert borrowed_token.balanceOf(user1) == user1_borrowed


def test_zap_cannot_borrow_more_on_another_users_position(
    open_position,
    funded_user,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """
    user2 leveraging through the zap creates a loan for user2. user1's approved position
    and his wallet are untouched, even though the zap can move both of their tokens.
    """
    user1 = open_position()
    user2 = funded_user()
    approve_zap(user2, controller, leverage_zap, collateral_token, borrowed_token)

    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    user1_state = controller.user_state(user1)
    user1_collateral = collateral_token.balanceOf(user1)

    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    collateral_out = collateral_from_borrowed(d_debt, price_oracle.price(), bd, cd)
    calldata = make_deposit_calldata(
        controller_id,
        collateral_out * 999 // 1000,
        dummy_router,
        borrowed_token,
        collateral_token,
        d_debt,
        collateral_out,
    )

    with boa.env.prank(user2):
        leverage_zap.create_loan(controller_id, user_collateral, d_debt, N, *calldata)

    # user2 got his own position, paid for out of his own wallet
    assert controller.loan_exists(user2)
    assert controller.user_state(user2)[0] == user_collateral + collateral_out
    # user1 is exactly where he was
    assert controller.user_state(user1) == user1_state
    assert collateral_token.balanceOf(user1) == user1_collateral
