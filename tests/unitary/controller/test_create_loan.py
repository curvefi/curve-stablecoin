import pytest
import boa
from eth_abi import encode

from tests.utils import max_approve, filter_logs
from tests.utils.constants import MIN_TICKS, MAX_TICKS

COLLATERAL = 10**17
DEBT = 10**20
N_BANDS = 6


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
    def fn(token, borrower, creator):
        return {
            "borrower": token.balanceOf(borrower),
            "creator": token.balanceOf(creator),
            "controller": token.balanceOf(controller),
            "amm": token.balanceOf(amm),
            "callback": token.balanceOf(dummy_callback),
        }

    return fn


@pytest.mark.parametrize("different_creator", [True, False])
def test_create_loan(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    snapshot,
    different_creator,
    monetary_policy,
    admin,
):
    """
    Test loan creation using wallet collateral.

    Money Flow: collateral (creator) → AMM
                debt (Controller) → Borrower
                Position is created
    """
    borrower = boa.env.eoa
    creator = borrower
    if different_creator:
        creator = boa.env.generate_address()

    # ================= Capture initial state =================

    assert controller.n_loans() == 0
    assert not controller.loan_exists(borrower)
    total_debt_before = controller.total_debt()
    initial_lent = controller.eval("core.lent")
    initial_amm_rate = amm.rate()
    initial_amm_rate_time = amm.eval("self.rate_time")

    # ================= Change rate =================

    # Increase rate_time and rate by 1
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1, sender=admin)

    # ================= Setup creator tokens =================

    boa.deal(collateral_token, creator, COLLATERAL)
    max_approve(collateral_token, controller, sender=creator)

    # ================= Calculate future health =================

    preview_health = controller.create_loan_health_preview(COLLATERAL, DEBT, N_BANDS, False)
    preview_health_full = controller.create_loan_health_preview(
        COLLATERAL, DEBT, N_BANDS, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, creator)
    collateral_token_before = snapshot(collateral_token, borrower, creator)

    # ================= Execute loan creation =================

    if different_creator:
        # Can't create loan for different user without approval
        with boa.reverts():
            controller.create_loan(COLLATERAL, DEBT, N_BANDS, borrower, sender=creator)
        controller.approve(creator, True, sender=borrower)

    controller.create_loan(COLLATERAL, DEBT, N_BANDS, borrower, sender=creator)

    # ================= Capture logs =================

    borrow_logs = filter_logs(controller, "Borrow")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, creator)
    collateral_token_after = snapshot(collateral_token, borrower, creator)

    # ================= Calculate money flows =================

    borrowed_to_borrower = (
        borrowed_token_after["borrower"] - borrowed_token_before["borrower"]
    )
    borrowed_from_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    collateral_to_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_from_creator = (
        collateral_token_after["creator"] - collateral_token_before["creator"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == COLLATERAL  # collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM initially
    assert user_state_after[2] == DEBT  # debt created
    assert user_state_after[3] == N_BANDS  # N bands
    assert controller.total_debt() == total_debt_before + DEBT
    assert controller.eval("core.lent") == initial_lent + DEBT
    assert controller.debt(borrower) == DEBT
    assert controller.n_loans() == 1
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
    assert borrow_logs[0].collateral_increase == COLLATERAL
    assert borrow_logs[0].loan_increase == DEBT

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == COLLATERAL
    assert state_logs[0].borrowed == 0
    assert state_logs[0].debt == DEBT
    assert state_logs[0].n2 - state_logs[0].n1 + 1 == N_BANDS
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(borrower)

    # ================= Verify money flows =================

    assert borrowed_to_borrower == DEBT
    assert borrowed_from_controller == -DEBT
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_amm == COLLATERAL
    assert collateral_from_creator == -COLLATERAL
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]

    if different_creator:
        assert borrowed_token_after["creator"] == borrowed_token_before["creator"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_creator", [True, False])
def test_create_loan_with_callback(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    snapshot,
    dummy_callback,
    get_calldata,
    different_creator,
    monetary_policy,
    admin,
):
    """
    Test loan creation using callback to provide additional collateral.

    Money Flow: collateral (creator) → AMM
                debt (Controller) → Callback
                additional_collateral (callback) → AMM
                Position is created with more collateral
    """
    borrower = boa.env.eoa
    creator = borrower
    if different_creator:
        creator = boa.env.generate_address()

    # ================= Capture initial state =================

    assert controller.n_loans() == 0
    assert not controller.loan_exists(borrower)
    total_debt_before = controller.total_debt()
    initial_lent = controller.eval("core.lent")
    initial_amm_rate = amm.rate()
    initial_amm_rate_time = amm.eval("self.rate_time")
    callback_hits = dummy_callback.callback_deposit_hits()

    # ================= Change rate =================

    # Increase rate_time and rate by 1
    boa.env.time_travel(1)
    monetary_policy.set_rate(initial_amm_rate + 1, sender=admin)

    # ================= Setup creator tokens =================

    wallet_collateral = COLLATERAL
    callback_collateral = COLLATERAL // 3
    total_collateral = wallet_collateral + callback_collateral
    boa.deal(collateral_token, creator, wallet_collateral)
    max_approve(collateral_token, controller, sender=creator)

    # ================= Setup callback tokens =================

    calldata = get_calldata(0, callback_collateral)
    boa.deal(collateral_token, dummy_callback, callback_collateral)

    # ================= Calculate future health =================

    preview_health = controller.create_loan_health_preview(
        total_collateral, DEBT, N_BANDS, False
    )
    preview_health_full = controller.create_loan_health_preview(
        total_collateral, DEBT, N_BANDS, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, creator)
    collateral_token_before = snapshot(collateral_token, borrower, creator)

    # ================= Execute loan creation via callback =================

    if different_creator:
        # Can't create loan for different user without approval
        with boa.reverts():
            controller.create_loan(
                wallet_collateral,
                DEBT,
                N_BANDS,
                borrower,
                dummy_callback,
                calldata,
                sender=creator,
            )
        controller.approve(creator, True, sender=borrower)

    controller.create_loan(
        wallet_collateral, DEBT, N_BANDS, borrower, dummy_callback, calldata, sender=creator
    )

    # ================= Capture logs =================

    borrow_logs = filter_logs(controller, "Borrow")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, creator)
    collateral_token_after = snapshot(collateral_token, borrower, creator)

    # ================= Calculate money flows =================

    borrowed_to_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    borrowed_from_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    collateral_to_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_from_creator = (
        collateral_token_after["creator"] - collateral_token_before["creator"]
    )
    collateral_from_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == total_collateral  # collateral in AMM (wallet + callback)
    assert user_state_after[1] == 0  # no borrowed tokens in AMM initially
    assert user_state_after[2] == DEBT  # debt created
    assert user_state_after[3] == N_BANDS  # N bands
    assert controller.total_debt() == total_debt_before + DEBT
    assert controller.eval("core.lent") == initial_lent + DEBT
    assert controller.debt(borrower) == DEBT
    assert controller.n_loans() == 1
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
    assert borrow_logs[0].loan_increase == DEBT

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == total_collateral
    assert state_logs[0].borrowed == 0
    assert state_logs[0].debt == DEBT
    assert state_logs[0].n2 - state_logs[0].n1 + 1 == N_BANDS
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(borrower)

    # ================= Verify money flows =================

    assert borrowed_to_callback == DEBT
    assert borrowed_from_controller == -DEBT
    assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_amm == total_collateral
    assert collateral_from_creator == -wallet_collateral
    assert collateral_from_callback == -callback_collateral
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_creator:
        assert borrowed_token_after["creator"] == borrowed_token_before["creator"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


def test_create_loan_already_exists(
    controller,
    collateral_token,
    borrowed_token,
):
    """
    Test that creating a loan when one already exists reverts.
    """
    borrower = boa.env.eoa
    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller, sender=borrower)

    # Create first loan
    controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=borrower)
    assert controller.loan_exists(borrower)

    # Try to create another loan - should revert
    with boa.reverts("Loan already created"):
        controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=borrower)


def test_create_loan_invalid_ticks(
    controller,
    collateral_token,
    borrowed_token,
):
    """
    Test that creating a loan with invalid number of ticks reverts.
    """
    borrower = boa.env.eoa
    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller, sender=borrower)

    # Too few ticks
    with boa.reverts("Need more ticks"):
        controller.create_loan(COLLATERAL, DEBT, MIN_TICKS - 1, sender=borrower)

    # Too many ticks
    with boa.reverts("Need less ticks"):
        controller.create_loan(COLLATERAL, DEBT, MAX_TICKS + 1, sender=borrower)


def test_create_loan_debt_too_high(
    controller,
    collateral_token,
    borrowed_token,
):
    """
    Test that creating a loan with debt too high reverts.
    """
    borrower = boa.env.eoa
    max_debt = controller.max_borrowable(COLLATERAL, N_BANDS)
    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller, sender=borrower)

    with boa.reverts("Debt too high"):
        controller.create_loan(COLLATERAL, max_debt * 1001 // 1000, N_BANDS, sender=borrower)

    # Works with max_debt
    controller.create_loan(COLLATERAL, max_debt, N_BANDS, sender=borrower)
