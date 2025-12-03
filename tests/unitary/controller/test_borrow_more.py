import pytest
import boa
from eth_abi import encode

from tests.utils import max_approve, filter_logs

COLLATERAL = 10**17
DEBT = 10**20
N_BANDS = 6
ADDITIONAL_COLLATERAL = 5 * 10**16  # Half of initial collateral
ADDITIONAL_DEBT = 5 * 10**19  # Half of initial debt


@pytest.fixture(scope="module")
def get_calldata(borrowed_token, collateral_token):
    def fn(borrowed_amount, collateral_amount):
        return encode(
            ["address", "address", "uint256", "uint256"],
            [
                borrowed_token.address,
                collateral_token.address,
                borrowed_amount,
                collateral_amount,
            ],
        )

    return fn


@pytest.fixture(scope="module")
def snapshot(controller, amm, dummy_callback):
    def fn(token, borrower, caller):
        return {
            "borrower": token.balanceOf(borrower),
            "caller": token.balanceOf(caller),
            "controller": token.balanceOf(controller),
            "amm": token.balanceOf(amm),
            "callback": token.balanceOf(dummy_callback),
        }

    return fn


@pytest.fixture(scope="function")
def borrower_with_existing_loan(controller, collateral_token):
    """
    Create an existing loan for testing borrow_more.
    """
    borrower = boa.env.eoa
    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller, sender=borrower)

    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=borrower)
    assert controller.loan_exists(borrower)
    assert controller.debt(borrower) == DEBT

    return borrower


@pytest.mark.parametrize("different_caller", [True, False])
def test_borrow_more_from_wallet(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    snapshot,
    borrower_with_existing_loan,
    different_caller,
    monetary_policy,
    admin,
):
    """
    Test borrowing more with collateral from wallet only.

    Money Flow: collateral (caller) → AMM
                debt (Controller) → Borrower
                Position collateral and debt increase
    """
    borrower = borrower_with_existing_loan
    caller = borrower
    if different_caller:
        caller = boa.env.generate_address()

    # ================= Change rate =================

    # Increase rate_time and rate by 1
    initial_amm_rate = amm.rate()
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1, sender=admin)

    # ================= Capture initial state =================

    assert controller.loan_exists(borrower)
    total_debt_before = controller.total_debt()
    initial_lent = controller.eval("core.lent")
    initial_amm_rate_time = amm.eval("self.rate_time")
    user_state_before = controller.user_state(borrower)
    initial_collateral = user_state_before[0]
    initial_debt = user_state_before[2]

    # ================= Setup caller tokens =================

    boa.deal(collateral_token, caller, ADDITIONAL_COLLATERAL)
    max_approve(collateral_token, controller, sender=caller)

    # ================= Calculate future health =================

    preview_health = controller.borrow_more_health_preview(
        ADDITIONAL_COLLATERAL, ADDITIONAL_DEBT, borrower, False
    )
    preview_health_full = controller.borrow_more_health_preview(
        ADDITIONAL_COLLATERAL, ADDITIONAL_DEBT, borrower, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, caller)
    collateral_token_before = snapshot(collateral_token, borrower, caller)

    # ================= Execute borrow_more =================

    if different_caller:
        # Can't borrow more for different user without approval
        with boa.reverts():
            controller.borrow_more(
                ADDITIONAL_COLLATERAL, ADDITIONAL_DEBT, borrower, sender=caller
            )
        controller.approve(caller, True, sender=borrower)

    controller.borrow_more(ADDITIONAL_COLLATERAL, ADDITIONAL_DEBT, borrower, sender=caller)

    # ================= Capture logs =================

    borrow_logs = filter_logs(controller, "Borrow")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, caller)
    collateral_token_after = snapshot(collateral_token, borrower, caller)

    # ================= Calculate money flows =================

    borrowed_to_borrower = (
        borrowed_token_after["borrower"] - borrowed_token_before["borrower"]
    )
    borrowed_from_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    collateral_to_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_from_caller = (
        collateral_token_after["caller"] - collateral_token_before["caller"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert (
        user_state_after[0] == initial_collateral + ADDITIONAL_COLLATERAL
    )  # collateral increased
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == initial_debt + ADDITIONAL_DEBT  # debt increased
    assert user_state_after[3] == N_BANDS  # N bands unchanged
    assert controller.total_debt() == total_debt_before + ADDITIONAL_DEBT
    assert controller.eval("core.lent") == initial_lent + ADDITIONAL_DEBT
    assert controller.debt(borrower) == initial_debt + ADDITIONAL_DEBT
    assert controller.loan_exists(borrower)
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # ================= Verify logs =================

    assert len(borrow_logs) == 1
    assert borrow_logs[0].user == borrower
    assert borrow_logs[0].collateral_increase == ADDITIONAL_COLLATERAL
    assert borrow_logs[0].loan_increase == ADDITIONAL_DEBT

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == initial_collateral + ADDITIONAL_COLLATERAL
    assert state_logs[0].borrowed == 0
    assert state_logs[0].debt == initial_debt + ADDITIONAL_DEBT
    assert state_logs[0].n2 - state_logs[0].n1 + 1 == N_BANDS
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    # ================= Verify money flows =================

    assert borrowed_to_borrower == ADDITIONAL_DEBT
    assert borrowed_from_controller == -ADDITIONAL_DEBT
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_amm == ADDITIONAL_COLLATERAL
    assert collateral_from_caller == -ADDITIONAL_COLLATERAL
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]

    if different_caller:
        assert borrowed_token_after["caller"] == borrowed_token_before["caller"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_caller", [True, False])
def test_borrow_more_from_callback(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    snapshot,
    borrower_with_existing_loan,
    dummy_callback,
    get_calldata,
    different_caller,
    monetary_policy,
    admin,
):
    """
    Test borrowing more with collateral from callback only.

    Money Flow: debt (Controller) → Callback
                collateral (callback) → AMM
                Position collateral and debt increase
    """
    borrower = borrower_with_existing_loan
    caller = borrower
    if different_caller:
        caller = boa.env.generate_address()

    # ================= Change rate =================

    # Increase rate_time and rate by 1
    initial_amm_rate = amm.rate()
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1, sender=admin)

    # ================= Capture initial state =================

    assert controller.loan_exists(borrower)
    total_debt_before = controller.total_debt()
    initial_lent = controller.eval("core.lent")
    initial_amm_rate_time = amm.eval("self.rate_time")
    user_state_before = controller.user_state(borrower)
    initial_collateral = user_state_before[0]
    initial_debt = user_state_before[2]
    callback_hits = dummy_callback.callback_deposit_hits()

    # ================= Setup callback tokens =================

    callback_collateral = ADDITIONAL_COLLATERAL
    total_collateral = callback_collateral
    calldata = get_calldata(0, callback_collateral)
    boa.deal(collateral_token, dummy_callback, callback_collateral)

    # ================= Calculate future health =================

    preview_health = controller.borrow_more_health_preview(
        total_collateral, ADDITIONAL_DEBT, borrower, False
    )
    preview_health_full = controller.borrow_more_health_preview(
        total_collateral, ADDITIONAL_DEBT, borrower, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, caller)
    collateral_token_before = snapshot(collateral_token, borrower, caller)

    # ================= Execute borrow_more via callback =================

    if different_caller:
        # Can't borrow more for different user without approval
        with boa.reverts():
            controller.borrow_more(
                0,
                ADDITIONAL_DEBT,
                borrower,
                dummy_callback,
                calldata,
                sender=caller,
            )
        controller.approve(caller, True, sender=borrower)

    controller.borrow_more(
        0,
        ADDITIONAL_DEBT,
        borrower,
        dummy_callback,
        calldata,
        sender=caller,
    )

    # ================= Capture logs =================

    borrow_logs = filter_logs(controller, "Borrow")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, caller)
    collateral_token_after = snapshot(collateral_token, borrower, caller)

    # ================= Calculate money flows =================

    borrowed_to_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    borrowed_from_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    collateral_to_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_from_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert (
        user_state_after[0] == initial_collateral + total_collateral
    )  # collateral increased (callback only)
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == initial_debt + ADDITIONAL_DEBT  # debt increased
    assert user_state_after[3] == N_BANDS  # N bands unchanged
    assert controller.total_debt() == total_debt_before + ADDITIONAL_DEBT
    assert controller.eval("core.lent") == initial_lent + ADDITIONAL_DEBT
    assert controller.debt(borrower) == initial_debt + ADDITIONAL_DEBT
    assert controller.loan_exists(borrower)
    assert dummy_callback.callback_deposit_hits() == callback_hits + 1
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # ================= Verify logs =================

    assert len(borrow_logs) == 1
    assert borrow_logs[0].user == borrower
    assert borrow_logs[0].collateral_increase == total_collateral
    assert borrow_logs[0].loan_increase == ADDITIONAL_DEBT

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == initial_collateral + total_collateral
    assert state_logs[0].borrowed == 0
    assert state_logs[0].debt == initial_debt + ADDITIONAL_DEBT
    assert state_logs[0].n2 - state_logs[0].n1 + 1 == N_BANDS
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    # ================= Verify money flows =================

    assert borrowed_to_callback == ADDITIONAL_DEBT
    assert borrowed_from_controller == -ADDITIONAL_DEBT
    assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_amm == total_collateral
    assert collateral_from_callback == -callback_collateral
    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_caller:
        assert borrowed_token_after["caller"] == borrowed_token_before["caller"]
        assert collateral_token_after["caller"] == collateral_token_before["caller"]


@pytest.mark.parametrize("different_caller", [True, False])
def test_borrow_more_from_wallet_and_callback(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    snapshot,
    borrower_with_existing_loan,
    dummy_callback,
    get_calldata,
    different_caller,
    monetary_policy,
    admin,
):
    """
    Test borrowing more with collateral from both wallet and callback.

    Money Flow: collateral (caller) → AMM
                debt (Controller) → Callback
                additional_collateral (callback) → AMM
                Position collateral and debt increase
    """
    borrower = borrower_with_existing_loan
    caller = borrower
    if different_caller:
        caller = boa.env.generate_address()

    # ================= Change rate =================

    # Increase rate_time and rate by 1
    initial_amm_rate = amm.rate()
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1, sender=admin)

    # ================= Capture initial state =================

    assert controller.loan_exists(borrower)
    total_debt_before = controller.total_debt()
    initial_lent = controller.eval("core.lent")
    initial_amm_rate_time = amm.eval("self.rate_time")
    user_state_before = controller.user_state(borrower)
    initial_collateral = user_state_before[0]
    initial_debt = user_state_before[2]
    callback_hits = dummy_callback.callback_deposit_hits()

    # ================= Setup caller tokens =================

    wallet_collateral = ADDITIONAL_COLLATERAL
    callback_collateral = ADDITIONAL_COLLATERAL // 3
    total_collateral = wallet_collateral + callback_collateral
    boa.deal(collateral_token, caller, wallet_collateral)
    max_approve(collateral_token, controller, sender=caller)

    # ================= Setup callback tokens =================

    calldata = get_calldata(0, callback_collateral)
    boa.deal(collateral_token, dummy_callback, callback_collateral)

    # ================= Calculate future health =================

    preview_health = controller.borrow_more_health_preview(
        total_collateral, ADDITIONAL_DEBT, borrower, False
    )
    preview_health_full = controller.borrow_more_health_preview(
        total_collateral, ADDITIONAL_DEBT, borrower, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, caller)
    collateral_token_before = snapshot(collateral_token, borrower, caller)

    # ================= Execute borrow_more via callback =================

    if different_caller:
        # Can't borrow more for different user without approval
        with boa.reverts():
            controller.borrow_more(
                wallet_collateral,
                ADDITIONAL_DEBT,
                borrower,
                dummy_callback,
                calldata,
                sender=caller,
            )
        controller.approve(caller, True, sender=borrower)

    controller.borrow_more(
        wallet_collateral,
        ADDITIONAL_DEBT,
        borrower,
        dummy_callback,
        calldata,
        sender=caller,
    )

    # ================= Capture logs =================

    borrow_logs = filter_logs(controller, "Borrow")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, caller)
    collateral_token_after = snapshot(collateral_token, borrower, caller)

    # ================= Calculate money flows =================

    borrowed_to_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    borrowed_from_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    collateral_to_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_from_caller = (
        collateral_token_after["caller"] - collateral_token_before["caller"]
    )
    collateral_from_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert (
        user_state_after[0] == initial_collateral + total_collateral
    )  # collateral increased (wallet + callback)
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == initial_debt + ADDITIONAL_DEBT  # debt increased
    assert user_state_after[3] == N_BANDS  # N bands unchanged
    assert controller.total_debt() == total_debt_before + ADDITIONAL_DEBT
    assert controller.eval("core.lent") == initial_lent + ADDITIONAL_DEBT
    assert controller.debt(borrower) == initial_debt + ADDITIONAL_DEBT
    assert controller.loan_exists(borrower)
    assert dummy_callback.callback_deposit_hits() == callback_hits + 1
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # ================= Verify logs =================

    assert len(borrow_logs) == 1
    assert borrow_logs[0].user == borrower
    assert borrow_logs[0].collateral_increase == total_collateral
    assert borrow_logs[0].loan_increase == ADDITIONAL_DEBT

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == initial_collateral + total_collateral
    assert state_logs[0].borrowed == 0
    assert state_logs[0].debt == initial_debt + ADDITIONAL_DEBT
    assert state_logs[0].n2 - state_logs[0].n1 + 1 == N_BANDS
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    # ================= Verify money flows =================

    assert borrowed_to_callback == ADDITIONAL_DEBT
    assert borrowed_from_controller == -ADDITIONAL_DEBT
    assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_amm == total_collateral
    assert collateral_from_caller == -wallet_collateral
    assert collateral_from_callback == -callback_collateral
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_caller:
        assert borrowed_token_after["caller"] == borrowed_token_before["caller"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


def test_borrow_more_no_loan_exists(
    controller,
    collateral_token,
    borrowed_token,
):
    """
    Test that borrowing more when no loan exists reverts.
    """
    borrower = boa.env.eoa
    boa.deal(collateral_token, borrower, ADDITIONAL_COLLATERAL)
    max_approve(collateral_token, controller, sender=borrower)

    assert not controller.loan_exists(borrower)

    # Try to borrow more without a loan - should revert
    with boa.reverts("Loan doesn't exist"):
        controller.borrow_more(ADDITIONAL_COLLATERAL, ADDITIONAL_DEBT, sender=borrower)


def test_borrow_more_zero_debt(
    controller,
    collateral_token,
    borrower_with_existing_loan,
):
    """
    Test that borrowing zero debt does nothing (early return).
    """
    borrower = borrower_with_existing_loan
    user_state_before = controller.user_state(borrower)
    initial_collateral = user_state_before[0]
    initial_debt = user_state_before[2]

    # Borrow zero debt - should return early without error
    controller.borrow_more(ADDITIONAL_COLLATERAL, 0, sender=borrower)

    # State should be unchanged (collateral not added when debt is 0)
    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == initial_collateral
    assert user_state_after[2] == initial_debt


def test_borrow_more_underwater(
    controller,
    amm,
    borrowed_token,
    collateral_token,
):
    """
    Test that borrowing more when position is underwater reverts.
    """

    # ================= Create loan with max debt =================

    borrower = boa.env.eoa
    max_debt = controller.max_borrowable(COLLATERAL, N_BANDS)
    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller, sender=borrower)

    controller.create_loan(COLLATERAL, max_debt, N_BANDS, sender=borrower)

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    # Verify position is underwater (xy[0] > 0)
    user_state = controller.user_state(borrower)
    assert user_state[1] > 0  # borrowed tokens in AMM > 0

    # ================= Execute borrow_more =================

    # Try to borrow more when underwater - should revert
    with boa.reverts("Underwater"):
        controller.borrow_more(ADDITIONAL_COLLATERAL, ADDITIONAL_DEBT, sender=borrower)

