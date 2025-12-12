import pytest
import boa
from tests.utils import max_approve, filter_logs


COLLATERAL = 10**17
DEBT = 10**20
N_BANDS = 6
REMOVE_COLLATERAL = 5 * 10**16  # Half of initial collateral


@pytest.fixture(scope="module")
def snapshot(controller, amm):
    def fn(token, borrower, caller):
        return {
            "borrower": token.balanceOf(borrower),
            "caller": token.balanceOf(caller),
            "controller": token.balanceOf(controller),
            "amm": token.balanceOf(amm),
        }

    return fn


@pytest.fixture(scope="function")
def borrower_with_existing_loan(controller, collateral_token):
    """
    Create an existing loan for testing remove_collateral.
    """
    borrower = boa.env.eoa
    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller, sender=borrower)

    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=borrower)
    assert controller.loan_exists(borrower)
    assert controller.debt(borrower) == DEBT

    return borrower


@pytest.mark.parametrize("different_caller", [True, False])
def test_remove_collateral(
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
    Test removing collateral from an existing loan.

    Money Flow: collateral (AMM) → borrower
                Position collateral decreases
                Debt remains unchanged
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

    # ================= Calculate future health =================

    preview_health = controller.remove_collateral_health_preview(
        REMOVE_COLLATERAL, borrower, False
    )
    preview_health_full = controller.remove_collateral_health_preview(
        REMOVE_COLLATERAL, borrower, True
    )
    # health decreases
    assert preview_health_full < controller.health(borrower, True)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, caller)
    collateral_token_before = snapshot(collateral_token, borrower, caller)

    # ================= Execute remove_collateral =================

    if different_caller:
        # Can't remove collateral for different user without approval
        with boa.reverts():
            controller.remove_collateral(REMOVE_COLLATERAL, borrower, sender=caller)
        controller.approve(caller, True, sender=borrower)

    controller.remove_collateral(REMOVE_COLLATERAL, borrower, sender=caller)

    # ================= Capture logs =================

    remove_collateral_logs = filter_logs(controller, "RemoveCollateral")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, caller)
    collateral_token_after = snapshot(collateral_token, borrower, caller)

    # ================= Calculate money flows =================

    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert (
        user_state_after[0] == initial_collateral - REMOVE_COLLATERAL
    )  # collateral decreased
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == initial_debt  # debt unchanged
    assert user_state_after[3] == N_BANDS  # N bands unchanged
    assert controller.total_debt() == total_debt_before  # total debt unchanged
    assert controller.eval("core.lent") == initial_lent  # lent unchanged
    assert controller.debt(borrower) == initial_debt  # user debt unchanged
    assert controller.loan_exists(borrower)
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )
    assert amm.eval("self.rate_time") > initial_amm_rate_time
    assert amm.rate() == initial_amm_rate + 1

    # ================= Verify logs =================

    assert len(remove_collateral_logs) == 1
    assert remove_collateral_logs[0].user == borrower
    assert remove_collateral_logs[0].collateral_decrease == REMOVE_COLLATERAL

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == initial_collateral - REMOVE_COLLATERAL
    assert state_logs[0].borrowed == 0
    assert state_logs[0].debt == initial_debt
    assert state_logs[0].n2 - state_logs[0].n1 + 1 == N_BANDS
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    # ================= Verify money flows =================

    assert collateral_from_amm == -REMOVE_COLLATERAL
    assert collateral_to_borrower == REMOVE_COLLATERAL
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["controller"] == borrowed_token_before["controller"]

    if different_caller:
        assert borrowed_token_after["caller"] == borrowed_token_before["caller"]
        assert collateral_token_after["caller"] == collateral_token_before["caller"]


def test_remove_collateral_no_loan_exists(
    controller,
    collateral_token,
    borrowed_token,
):
    """
    Test that removing collateral when no loan exists reverts.
    """
    borrower = boa.env.eoa

    assert not controller.loan_exists(borrower)

    # Try to remove collateral without a loan - should revert
    with boa.reverts("Loan doesn't exist"):
        controller.remove_collateral(REMOVE_COLLATERAL, sender=borrower)


def test_remove_collateral_zero_amount(
    controller,
    collateral_token,
    borrower_with_existing_loan,
):
    """
    Test that removing zero collateral does nothing (early return).
    """
    borrower = borrower_with_existing_loan
    user_state_before = controller.user_state(borrower)
    initial_collateral = user_state_before[0]

    # Remove zero collateral - should return early without error
    controller.remove_collateral(0, sender=borrower)

    # State should be unchanged
    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == initial_collateral


def test_remove_collateral_too_much(
    controller,
    collateral_token,
    borrower_with_existing_loan,
):
    """
    Test that removing more collateral than available reverts.
    """
    borrower = borrower_with_existing_loan
    user_state_before = controller.user_state(borrower)
    initial_collateral = user_state_before[0]

    # Can't keep the same debt with that low collateral amount
    with boa.reverts("Debt too high"):
        controller.remove_collateral(initial_collateral * 9 // 10, sender=borrower)

    # Try to remove more collateral than available - should revert
    with boa.reverts():
        controller.remove_collateral(initial_collateral + 1, sender=borrower)


def test_remove_collateral_underwater(
    controller,
    amm,
    borrowed_token,
    collateral_token,
):
    """
    Test that removing collateral when position is underwater reverts.
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

    # ================= Execute remove_collateral =================

    # Try to remove collateral when underwater - should revert
    with boa.reverts("Underwater"):
        controller.remove_collateral(REMOVE_COLLATERAL, sender=borrower)
