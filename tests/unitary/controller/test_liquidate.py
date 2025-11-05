import pytest
import boa
from eth_abi import encode

from tests.utils import max_approve, filter_logs
from tests.utils.constants import MAX_UINT256, ZERO_ADDRESS, WAD

COLLATERAL = 10**17
N_BANDS = 6


@pytest.fixture(scope="module")
def create_loan(controller, collateral_token, borrowed_token):
    def fn(max_debt=False):
        borrower = boa.env.eoa
        boa.deal(collateral_token, borrower, COLLATERAL)
        max_approve(collateral_token, controller)
        max_approve(borrowed_token, controller)
        debt = 10**18
        if max_debt:
            debt = controller.max_borrowable(COLLATERAL, N_BANDS)
        controller.create_loan(COLLATERAL, debt, N_BANDS)
        assert debt == controller.debt(borrower)
        return borrower

    return fn


@pytest.fixture(scope="module")
def get_calldata(dummy_callback, borrowed_token, collateral_token):
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
    def fn(token, borrower, liquidator):
        return {
            "borrower": token.balanceOf(borrower),
            "liquidator": token.balanceOf(liquidator),
            "controller": token.balanceOf(controller),
            "amm": token.balanceOf(amm),
            "callback": token.balanceOf(dummy_callback),
        }

    return fn


# ================= FULL LIQUIDATION =================

@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_wallet_healthy(
    controller, amm, borrowed_token, collateral_token, create_loan, snapshot, different_liquidator
):
    """
    Test full liquidation using wallet tokens.

    Money Flow: debt (liquidator) → Controller
                COLLATERAL (AMM) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan()

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert user_state_before[1] == 0 and user_state_before[0] > 0  # Position is not underwater
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup liquidator tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower)
    if different_liquidator:
        boa.deal(borrowed_token, liquidator, tokens_needed)
        max_approve(borrowed_token, controller, sender=liquidator)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation =================

    if different_liquidator:
        # Can't liquidate healthy users without approval
        with boa.reverts("Not enough rekt"):
            controller.liquidate(borrower, user_state_before[1], sender=liquidator)
        controller.approve(liquidator, True, sender=borrower)
    controller.liquidate(borrower, user_state_before[1], sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_liquidator == -debt
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == user_state_before[0]
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_wallet_unhealthy(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, different_liquidator
):
    """
    Test full liquidation using wallet tokens.

    Money Flow: debt (liquidator) → Controller
                COLLATERAL (AMM) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Lower oracle price to make position unhealthy =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert user_state_before[1] == 0 and user_state_before[0] > 0  # Position is not underwater
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup liquidator tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower)
    if different_liquidator:
        boa.deal(borrowed_token, liquidator, tokens_needed)
        max_approve(borrowed_token, controller, sender=liquidator)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation =================

    # Can liquidate unhealthy users without approval
    controller.liquidate(borrower, user_state_before[1], sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_liquidator == -debt
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == user_state_before[0]
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_wallet_healthy_underwater(
    controller, amm, borrowed_token, collateral_token, create_loan, snapshot, different_liquidator
):
    """
    Test full liquidation using wallet tokens.

    Money Flow: debt (liquidator) → Controller
                borrowed (AMM) → Controller
                COLLATERAL (AMM) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt // 10)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 10, 0)

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0  # Position is underwater
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup liquidator tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower)
    assert tokens_needed == debt - user_state_before[1]
    if different_liquidator:
        boa.deal(borrowed_token, liquidator, tokens_needed)
        max_approve(borrowed_token, controller, sender=liquidator)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation =================

    if different_liquidator:
        # Can't liquidate healthy users without approval
        with boa.reverts("Not enough rekt"):
            controller.liquidate(borrower, user_state_before[1], sender=liquidator)
        controller.approve(liquidator, True, sender=borrower)
    controller.liquidate(borrower, user_state_before[1], sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_liquidator == -tokens_needed
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == user_state_before[0]
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_wallet_unhealthy_underwater(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, different_liquidator
):
    """
    Test full liquidation using wallet tokens.

    Money Flow: debt (liquidator) → Controller
                borrowed (AMM) → Controller
                COLLATERAL (AMM) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Lower oracle price to make position unhealthy =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt // 10)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 10, 0)

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0  # Position is underwater
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")
    assert controller.health(borrower) < 0

    # ================= Setup liquidator tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower)
    assert tokens_needed == debt - user_state_before[1]
    if different_liquidator:
        boa.deal(borrowed_token, liquidator, tokens_needed)
        max_approve(borrowed_token, controller, sender=liquidator)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation =================

    # Can liquidate unhealthy users without approval
    controller.liquidate(borrower, user_state_before[1], sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_liquidator == -tokens_needed
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == user_state_before[0]
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_callback_healthy(
    controller, amm, borrowed_token, collateral_token, create_loan, snapshot, dummy_callback, get_calldata, different_liquidator
):
    """
    Test full liquidation using callback proceeds (no wallet tokens needed).

    Money Flow: debt (callbacker) → Controller
                COLLATERAL (callbacker, sourced from AMM) → Liquidator
                Surplus borrowed (callbacker) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan()

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert user_state_before[1] == 0 and user_state_before[0] > 0  # Not underwater
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")
    liquidate_hits = dummy_callback.callback_liquidate_hits()

    # ================= Setup callback tokens =================

    callback_collateral = COLLATERAL // 3
    tokens_needed = controller.tokens_to_liquidate(borrower)
    assert tokens_needed == debt
    profit = 1
    callback_borrowed = tokens_needed + profit
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    if different_liquidator:
        # Can't liquidate healthy users without approval
        with boa.reverts("Not enough rekt"):
            controller.liquidate(borrower, user_state_before[1], WAD, dummy_callback, calldata, sender=liquidator)
        controller.approve(liquidator, True, sender=borrower)
    controller.liquidate(borrower, user_state_before[1], WAD, dummy_callback, calldata, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_to_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_to_callback = (
            collateral_token_after["callback"] - collateral_token_before["callback"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt
    assert dummy_callback.callback_liquidate_hits() == liquidate_hits + 1

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_to_liquidator == profit
    assert borrowed_from_callback == -callback_borrowed  # callback drained by controller and forwarded surplus
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_callback == user_state_before[0] - callback_collateral
    assert collateral_to_liquidator == callback_collateral
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_callback_unhealthy(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, dummy_callback, get_calldata, different_liquidator
):
    """
    Unhealthy position liquidated via callback.

    Money Flow: debt (callbacker) → Controller
                COLLATERAL (callbacker, sourced from AMM) → Liquidator
                Surplus borrowed (callbacker) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Lower oracle price to make position unhealthy =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert user_state_before[1] == 0 and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")
    liquidate_hits = dummy_callback.callback_liquidate_hits()

    # ================= Setup callback tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower)
    assert tokens_needed == debt
    profit = 1
    callback_collateral = COLLATERAL // 3
    callback_borrowed = tokens_needed + profit
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    # Can liquidate unhealthy without approval
    controller.liquidate(borrower, user_state_before[1], WAD, dummy_callback, calldata, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_to_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0
    assert user_state_after[1] == 0
    assert user_state_after[2] == 0
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt
    assert dummy_callback.callback_liquidate_hits() == liquidate_hits + 1

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_to_liquidator == profit
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_callback == user_state_before[0] - callback_collateral
    assert collateral_to_liquidator == callback_collateral
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_callback_healthy_underwater(
    controller, amm, borrowed_token, collateral_token, create_loan, snapshot, dummy_callback, get_calldata, different_liquidator
):
    """
    Healthy but underwater (due to AMM state) liquidated via callback.

    Money Flow: debt (callbacker) → Controller
                borrowed (AMM) → Controller
                COLLATERAL (callbacker, sourced from AMM) → Liquidator
                Surplus borrowed (callbacker) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    boa.deal(borrowed_token, trader, debt // 10)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 10, 0)

    assert controller.health(borrower) > 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")
    liquidate_hits = dummy_callback.callback_liquidate_hits()

    # ================= Setup callback tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower)
    assert tokens_needed == debt - user_state_before[1]
    profit = 1
    callback_collateral = COLLATERAL // 3
    callback_borrowed = tokens_needed + profit
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    if different_liquidator:
        with boa.reverts("Not enough rekt"):
            controller.liquidate(borrower, user_state_before[1], WAD, dummy_callback, calldata, sender=liquidator)
        controller.approve(liquidator, True, sender=borrower)
    controller.liquidate(borrower, user_state_before[1], WAD, dummy_callback, calldata, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    borrowed_to_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt
    assert dummy_callback.callback_liquidate_hits() == liquidate_hits + 1

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_to_liquidator == profit
    assert borrowed_from_callback == -callback_borrowed

    assert collateral_to_callback == user_state_before[0] - callback_collateral
    assert collateral_to_liquidator == callback_collateral
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_callback_unhealthy_underwater(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, dummy_callback, get_calldata, different_liquidator
):
    """
    Unhealthy and underwater liquidation via callback.

    Money Flow: debt (callbacker) → Controller
                borrowed (AMM) → Controller
                COLLATERAL (callbacker, sourced from AMM) → Liquidator
                Surplus borrowed (callbacker) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Lower oracle price to make position unhealthy =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    boa.deal(borrowed_token, trader, debt // 10)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 10, 0)

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")
    liquidate_hits = dummy_callback.callback_liquidate_hits()

    # ================= Setup callback tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower)
    assert tokens_needed == debt - user_state_before[1]
    profit = 1
    callback_collateral = COLLATERAL // 3
    callback_borrowed = tokens_needed + profit
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    # Can liquidate unhealthy without approval
    controller.liquidate(borrower, user_state_before[1], WAD, dummy_callback, calldata, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    borrowed_to_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt
    assert dummy_callback.callback_liquidate_hits() == liquidate_hits + 1

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_to_liquidator == profit
    assert borrowed_from_callback == -callback_borrowed

    assert collateral_to_callback == user_state_before[0] - callback_collateral
    assert collateral_to_liquidator == callback_collateral
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_xy0_healthy_underwater(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, get_calldata, different_liquidator
):
    """
    Healthy but underwater position where borrowed tokens in AMM exceed debt.
    No wallet tokens needed (tokens_needed == 0).

    Money Flow: borrowed (AMM) → Controller (debt amount)
                borrowed (AMM) → Liquidator (surplus)
                COLLATERAL (AMM) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt * 10_001 // 10_000)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt * 10_001 // 10_000, 0)

    assert controller.health(borrower) > 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert user_state_before[1] > debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    tokens_needed = controller.tokens_to_liquidate(borrower)
    assert tokens_needed == 0

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    if different_liquidator:
        with boa.reverts("Not enough rekt"):
            controller.liquidate(borrower, user_state_before[1], sender=liquidator)
        controller.approve(liquidator, True, sender=borrower)
    controller.liquidate(borrower, user_state_before[1], sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    borrowed_to_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_to_liquidator == user_state_before[1] - debt
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == user_state_before[0]
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_xy0_healthy_underwater_exact(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, get_calldata, different_liquidator
):
    """
    Healthy but underwater position where borrowed tokens in AMM exactly equal debt.
    No wallet tokens needed (tokens_needed == 0).

    Money Flow: borrowed (AMM) → Controller (debt amount)
                COLLATERAL (AMM) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt * 10_001 // 10_000)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt * 10_001 // 10_000, 0)

        _, x, d, _ = controller.user_state(borrower)
        max_approve(collateral_token, amm)
        amm.exchange_dy(1, 0, x - d + 1, MAX_UINT256)

    assert controller.health(borrower) > 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert user_state_before[1] == debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    tokens_needed = controller.tokens_to_liquidate(borrower)
    assert tokens_needed == 0

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    if different_liquidator:
        with boa.reverts("Not enough rekt"):
            controller.liquidate(borrower, user_state_before[1], sender=liquidator)
        controller.approve(liquidator, True, sender=borrower)
    controller.liquidate(borrower, user_state_before[1], sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -debt
    assert borrowed_token_after["liquidator"] == borrowed_token_before["liquidator"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == user_state_before[0]
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_xy0_unhealthy_underwater(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, get_calldata, different_liquidator
):
    """
    Unhealthy and underwater position where borrowed tokens in AMM exceed debt.
    No wallet tokens needed (tokens_needed == 0).

    Money Flow: borrowed (AMM) → Controller (debt amount)
                borrowed (AMM) → Liquidator (surplus)
                COLLATERAL (AMM) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Lower oracle price to make position unhealthy =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt * 10_001 // 10_000)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt * 10_001 // 10_000, 0)

    assert controller.health(borrower) < 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert user_state_before[1] > debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    tokens_needed = controller.tokens_to_liquidate(borrower)
    assert tokens_needed == 0

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    # Can liquidate unhealthy without approval
    controller.liquidate(borrower, user_state_before[1], sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    borrowed_to_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_to_liquidator == user_state_before[1] - debt
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == user_state_before[0]
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
def test_liquidate_full_from_xy0_unhealthy_underwater_exact(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, get_calldata, different_liquidator
):
    """
    Unhealthy and underwater position where borrowed tokens in AMM exactly equal debt.
    No wallet tokens needed (tokens_needed == 0).

    Money Flow: borrowed (AMM) → Controller (debt amount)
                COLLATERAL (AMM) → Liquidator
                Position is fully liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Lower oracle price to make position unhealthy =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt * 10_001 // 10_000)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt * 10_001 // 10_000, 0)

        _, x, d, _ = controller.user_state(borrower)
        max_approve(collateral_token, amm)
        amm.exchange_dy(1, 0, x - d + 2, MAX_UINT256)

    assert controller.health(borrower) < 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert user_state_before[1] == debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    tokens_needed = controller.tokens_to_liquidate(borrower)
    assert tokens_needed == 0

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    # Can liquidate unhealthy without approval
    controller.liquidate(borrower, user_state_before[1], sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")
    state_logs = filter_logs(controller, "UserState")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # no collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM
    assert user_state_after[2] == 0  # debt fully repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].collateral_decrease == user_state_before[0]
    assert repay_logs[0].loan_decrease == debt

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == user_state_before[0]
    assert liquidate_logs[0].borrowed_received == user_state_before[1]
    assert liquidate_logs[0].debt == debt

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -debt
    assert borrowed_token_after["liquidator"] == borrowed_token_before["liquidator"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == user_state_before[0]
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


# ================= PARTIAL LIQUIDATION =================

@pytest.fixture(scope="module")
def get_f_remove(controller):
    """
    Note. Approval is required to liquidate healthy users, so we always consider h = 0 for such cases.
    """
    def f(frac, borrower, sender, is_healthy=False):
        h = controller.liquidation_discounts(borrower)
        if is_healthy or borrower == sender or controller.approval(borrower, sender):
            h = 0

        return controller.eval(f"core._get_f_remove({frac}, {h})")

    return f


@pytest.mark.parametrize("different_liquidator", [True, False])
@pytest.mark.parametrize("frac", [25 * 10**16, 50 * 10**16, 75 * 10**16])  # 25%, 50%, 75%
def test_liquidate_partial_from_wallet_healthy(
    controller, amm, borrowed_token, collateral_token, create_loan, snapshot, different_liquidator, frac, get_f_remove
):
    """
    Test partial liquidation using wallet tokens.

    Money Flow: partial_debt (liquidator) → Controller
                partial_COLLATERAL (AMM) → Liquidator
                Position is partially liquidated
    """
    borrower = create_loan()

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt_before = user_state_before[2]
    assert user_state_before[1] == 0 and user_state_before[0] > 0  # Position is not underwater
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Calc tokens to remove from AMM =================

    f_remove = get_f_remove(frac, borrower, liquidator, is_healthy=True)
    collateral_to_remove = user_state_before[0] * f_remove // WAD

    # ================= Setup liquidator tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower, frac, sender=liquidator)
    debt_to_repay = (debt_before * frac + WAD - 1) // WAD
    assert tokens_needed == debt_to_repay

    if different_liquidator:
        boa.deal(borrowed_token, liquidator, tokens_needed)
        max_approve(borrowed_token, controller, sender=liquidator)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation =================

    if different_liquidator:
        # Can't liquidate healthy users without approval
        with boa.reverts("Not enough rekt"):
            controller.liquidate(borrower, 0, frac, sender=liquidator)
        controller.approve(liquidator, True, sender=borrower)
    controller.liquidate(borrower, 0, frac, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == pytest.approx(user_state_before[0] - collateral_to_remove, abs=3)  # some collateral remains in AMM
    assert user_state_after[1] == user_state_before[1] == 0
    assert user_state_after[2] == debt_before - debt_to_repay  # partial debt repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt_to_repay
    assert controller.eval("core.repaid") == repaid + debt_to_repay

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == debt_to_repay

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == pytest.approx(collateral_to_remove, abs=3)
    assert liquidate_logs[0].borrowed_received == 0  # No borrowed tokens in AMM for healthy positions
    assert liquidate_logs[0].debt == debt_to_repay

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt_to_repay
    assert borrowed_from_liquidator == -debt_to_repay
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == pytest.approx(collateral_to_remove, abs=3)
    assert collateral_from_amm == pytest.approx(-collateral_to_remove, abs=3)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
@pytest.mark.parametrize("frac", [25 * 10**16, 50 * 10**16, 75 * 10**16])  # 25%, 50%, 75%
def test_liquidate_partial_from_wallet_unhealthy(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, different_liquidator, frac, get_f_remove
):
    """
    Test partial liquidation using wallet tokens.

    Money Flow: partial_debt (liquidator) → Controller
                partial_COLLATERAL (AMM) → Liquidator
                Position is partially liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Lower oracle price to make position unhealthy =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt_before = user_state_before[2]
    assert user_state_before[1] == 0 and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Calc tokens to remove from AMM =================

    f_remove = get_f_remove(frac, borrower, liquidator)
    collateral_to_remove = user_state_before[0] * f_remove // WAD

    # ================= Setup liquidator tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower, frac, sender=liquidator)
    debt_to_repay = (debt_before * frac + WAD - 1) // WAD

    if different_liquidator:
        boa.deal(borrowed_token, liquidator, tokens_needed + 1)  # There is inaccuracy
        max_approve(borrowed_token, controller, sender=liquidator)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation =================

    # Can liquidate unhealthy users without approval
    controller.liquidate(borrower, 0, frac, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == pytest.approx(user_state_before[0] - collateral_to_remove, abs=5)  # some collateral remains in AMM
    assert user_state_after[1] == user_state_before[1] == 0
    assert user_state_after[2] == debt_before - debt_to_repay  # partial debt repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt_to_repay
    assert controller.eval("core.repaid") == repaid + debt_to_repay

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == debt_to_repay

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == pytest.approx(collateral_to_remove, abs=5)
    assert liquidate_logs[0].borrowed_received == 0  # No borrowed tokens in AMM for healthy positions
    assert liquidate_logs[0].debt == debt_to_repay

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt_to_repay
    assert borrowed_from_liquidator == -debt_to_repay
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == pytest.approx(collateral_to_remove, abs=5)
    assert collateral_from_amm == pytest.approx(-collateral_to_remove, abs=5)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
@pytest.mark.parametrize("frac", [25 * 10**16, 50 * 10**16, 75 * 10**16])  # 25%, 50%, 75%
def test_liquidate_partial_from_wallet_healthy_underwater(
    controller, amm, borrowed_token, collateral_token, create_loan, snapshot, different_liquidator, frac, get_f_remove
):
    """
    Test partial liquidation using wallet tokens.

    Money Flow: partial_debt (liquidator) → Controller
                partial_borrowed (AMM) → Controller
                partial_COLLATERAL (AMM) → Liquidator
                Position is partially liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt // 10)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 10, 0)

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt_before = user_state_before[2]
    assert 0 < user_state_before[1] < debt_before and user_state_before[0] > 0  # Position is underwater
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Calc tokens to remove from AMM =================

    f_remove = get_f_remove(frac, borrower, liquidator, is_healthy=True)
    collateral_to_remove = user_state_before[0] * f_remove // WAD
    borrowed_to_remove = user_state_before[1] * f_remove // WAD

    # ================= Setup liquidator tokens =================

    # Approval is required to liquidate healthy users,
    # so we pass sender=borrower to get the correct number as for approved user
    tokens_needed = controller.tokens_to_liquidate(borrower, frac, sender=borrower) + 1  # Inaccuracy
    debt_to_repay = (debt_before * frac + WAD - 1) // WAD
    assert 0 < tokens_needed == debt_to_repay - borrowed_to_remove

    if different_liquidator:
        boa.deal(borrowed_token, liquidator, tokens_needed)
        max_approve(borrowed_token, controller, sender=liquidator)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation =================

    if different_liquidator:
        # Can't liquidate healthy users without approval
        with boa.reverts("Not enough rekt"):
            controller.liquidate(borrower, 0, frac, sender=liquidator)
        controller.approve(liquidator, True, sender=borrower)
    controller.liquidate(borrower, 0, frac, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == pytest.approx(user_state_before[0] - collateral_to_remove, abs=3)
    assert user_state_after[1] == user_state_before[1] - borrowed_to_remove
    assert user_state_after[2] == debt_before - debt_to_repay  # partial debt repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt_to_repay
    assert controller.eval("core.repaid") == repaid + debt_to_repay

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == debt_to_repay

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == pytest.approx(collateral_to_remove, abs=3)  # collateral tokens withdrawn from AMM
    assert liquidate_logs[0].borrowed_received == borrowed_to_remove  # Borrowed tokens withdrawn from AMM
    assert liquidate_logs[0].debt == debt_to_repay

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt_to_repay
    assert borrowed_from_liquidator == pytest.approx(-tokens_needed, abs=1)
    assert borrowed_from_amm == -borrowed_to_remove
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == pytest.approx(collateral_to_remove, abs=3)
    assert collateral_from_amm == pytest.approx(-collateral_to_remove, abs=3)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
@pytest.mark.parametrize("frac", [25 * 10**16, 50 * 10**16, 75 * 10**16])  # 25%, 50%, 75%
def test_liquidate_partial_from_wallet_unhealthy_underwater(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, different_liquidator, frac, get_f_remove
):
    """
    Test partial liquidation using wallet tokens.

    Money Flow: partial_debt (liquidator) → Controller
                partial_borrowed (AMM) → Controller
                partial_COLLATERAL (AMM) → Liquidator
                Position is partially liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Lower oracle price to make position unhealthy =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt // 10)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 10, 0)
    assert controller.health(borrower) < 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt_before = user_state_before[2]
    assert 0 < user_state_before[1] < debt_before and user_state_before[0] > 0
    assert controller.health(borrower) < 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Calc tokens to removed from AMM =================

    f_remove = get_f_remove(frac, borrower, liquidator)
    collateral_to_remove = user_state_before[0] * f_remove // WAD
    borrowed_to_remove = user_state_before[1] * f_remove // WAD

    # ================= Setup liquidator tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower, frac, sender=liquidator)
    debt_to_repay = (debt_before * frac + WAD - 1) // WAD
    assert 0 < tokens_needed == pytest.approx(debt_to_repay - borrowed_to_remove, abs=1)

    if different_liquidator:
        boa.deal(borrowed_token, liquidator, tokens_needed + 1)  # There is inaccuracy
        max_approve(borrowed_token, controller, sender=liquidator)


    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation =================

    with boa.reverts("Slippage"):
        controller.liquidate(borrower, borrowed_to_remove + 1, frac, sender=liquidator)
    # Can liquidate unhealthy users without approval
    controller.liquidate(borrower, borrowed_to_remove, frac, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == pytest.approx(user_state_before[0] - collateral_to_remove, abs=5)
    assert user_state_after[1] == user_state_before[1] - borrowed_to_remove
    assert user_state_after[2] == debt_before - debt_to_repay  # partial debt repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt_to_repay
    assert controller.eval("core.repaid") == repaid + debt_to_repay

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == debt_to_repay

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == pytest.approx(collateral_to_remove, abs=3)
    assert liquidate_logs[0].borrowed_received == borrowed_to_remove  # Borrowed tokens withdrawn from AMM
    assert liquidate_logs[0].debt == debt_to_repay

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt_to_repay
    assert borrowed_from_liquidator == pytest.approx(-tokens_needed, abs=1)
    assert borrowed_from_amm == -borrowed_to_remove
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_liquidator == pytest.approx(collateral_to_remove, abs=3)
    assert collateral_from_amm == pytest.approx(-collateral_to_remove, abs=3)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
@pytest.mark.parametrize("frac", [25 * 10**16, 50 * 10**16, 75 * 10**16])  # 25%, 50%, 75%
def test_liquidate_partial_from_callback_healthy(
    controller, amm, borrowed_token, collateral_token, create_loan, snapshot, dummy_callback, get_calldata, different_liquidator, frac, get_f_remove
):
    """
    Test partial liquidation using callback proceeds (no wallet tokens needed).

    Money Flow: partial_debt (callbacker) → Controller
                partial_COLLATERAL (callbacker, sourced from AMM) → Liquidator
                Surplus borrowed (callbacker) → Liquidator
                Position is partially liquidated
    """
    borrower = create_loan()

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt_before = user_state_before[2]
    assert user_state_before[1] == 0 and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")
    liquidate_hits = dummy_callback.callback_liquidate_hits()

    # ================= Calc tokens to remove from AMM =================

    f_remove = get_f_remove(frac, borrower, liquidator, is_healthy=True)
    collateral_to_remove = user_state_before[0] * f_remove // WAD

    # ================= Setup callback tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower, frac, sender=liquidator)
    debt_to_repay = (debt_before * frac + WAD - 1) // WAD
    assert tokens_needed == debt_to_repay
    profit = 1
    callback_borrowed = tokens_needed + profit
    callback_collateral = collateral_to_remove // 3
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    if different_liquidator:
        # Can't liquidate healthy users without approval
        with boa.reverts("Not enough rekt"):
            controller.liquidate(borrower, 0, frac, dummy_callback, calldata, sender=liquidator)
        controller.approve(liquidator, True, sender=borrower)
    controller.liquidate(borrower, 0, frac, dummy_callback, calldata, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_to_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == pytest.approx(user_state_before[0] - collateral_to_remove, abs=3)  # some collateral remains in AMM
    assert user_state_after[1] == user_state_before[1] == 0
    assert user_state_after[2] == debt_before - debt_to_repay  # partial debt repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt_to_repay
    assert controller.eval("core.repaid") == repaid + debt_to_repay
    assert dummy_callback.callback_liquidate_hits() == liquidate_hits + 1

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == debt_to_repay

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == pytest.approx(collateral_to_remove, abs=3)
    assert liquidate_logs[0].borrowed_received == 0  # No borrowed tokens in AMM for healthy positions
    assert liquidate_logs[0].debt == debt_to_repay

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt_to_repay
    assert borrowed_to_liquidator == profit
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_liquidator == callback_collateral
    assert collateral_to_callback == pytest.approx(collateral_to_remove - callback_collateral, abs=3)
    assert collateral_from_amm == pytest.approx(-collateral_to_remove, abs=3)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
@pytest.mark.parametrize("frac", [25 * 10**16, 50 * 10**16, 75 * 10**16])  # 25%, 50%, 75%
def test_liquidate_partial_from_callback_unhealthy(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, dummy_callback, get_calldata, different_liquidator, frac, get_f_remove
):
    """
    Unhealthy position partially liquidated via callback.

    Money Flow: partial_debt (callbacker) → Controller
                partial_COLLATERAL (callbacker, sourced from AMM) → Liquidator
                Surplus borrowed (callbacker) → Liquidator
                Position is partially liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Lower oracle price to make position unhealthy =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt_before = user_state_before[2]
    assert user_state_before[1] == 0 and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")
    liquidate_hits = dummy_callback.callback_liquidate_hits()

    # ================= Calc tokens to remove from AMM =================

    f_remove = get_f_remove(frac, borrower, liquidator)
    collateral_to_remove = user_state_before[0] * f_remove // WAD

    # ================= Setup callback tokens =================

    # Inaccuracy
    tokens_needed = controller.tokens_to_liquidate(borrower, frac, sender=liquidator) + 1
    debt_to_repay = (debt_before * frac + WAD - 1) // WAD
    assert tokens_needed == debt_to_repay
    profit = 1
    callback_collateral = collateral_to_remove // 3
    callback_borrowed = tokens_needed + profit
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    # Can liquidate unhealthy without approval
    controller.liquidate(borrower, 0, frac, dummy_callback, calldata, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_to_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == pytest.approx(user_state_before[0] - collateral_to_remove, abs=5)  # some collateral remains in AMM
    assert user_state_after[1] == user_state_before[1] == 0
    assert user_state_after[2] == debt_before - debt_to_repay  # partial debt repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt_to_repay
    assert controller.eval("core.repaid") == repaid + debt_to_repay
    assert dummy_callback.callback_liquidate_hits() == liquidate_hits + 1

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == debt_to_repay

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == pytest.approx(collateral_to_remove, abs=3)
    assert liquidate_logs[0].borrowed_received == 0  # No borrowed tokens in AMM for healthy positions
    assert liquidate_logs[0].debt == debt_to_repay

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt_to_repay
    assert borrowed_to_liquidator == profit
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_liquidator == callback_collateral
    assert collateral_to_callback == pytest.approx(collateral_to_remove - callback_collateral, abs=3)
    assert collateral_from_amm == pytest.approx(-collateral_to_remove, abs=3)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
@pytest.mark.parametrize("frac", [25 * 10**16, 50 * 10**16, 75 * 10**16])  # 25%, 50%, 75%
def test_liquidate_partial_from_callback_healthy_underwater(
    controller, amm, borrowed_token, collateral_token, create_loan, snapshot, dummy_callback, get_calldata, different_liquidator, frac, get_f_remove
):
    """
    Healthy but underwater (due to AMM state) partially liquidated via callback.

    Money Flow: partial_debt (callbacker) → Controller
                partial_borrowed (AMM) → Controller
                partial_COLLATERAL (callbacker, sourced from AMM) → Liquidator
                Surplus borrowed (callbacker) → Liquidator
                Position is partially liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    boa.deal(borrowed_token, trader, debt // 10)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 10, 0)

    assert controller.health(borrower) > 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt_before = user_state_before[2]
    assert 0 < user_state_before[1] < debt_before and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")
    liquidate_hits = dummy_callback.callback_liquidate_hits()

    # ================= Calc tokens to removed from AMM =================

    f_remove = get_f_remove(frac, borrower, liquidator, is_healthy=True)
    collateral_to_remove = user_state_before[0] * f_remove // WAD
    borrowed_to_remove = user_state_before[1] * f_remove // WAD

    # ================= Setup callback tokens =================

    # Approval is required to liquidate healthy users,
    # so we pass sender=borrower to get the correct number as for approved user
    tokens_needed = controller.tokens_to_liquidate(borrower, frac, sender=borrower) + 1  # Inaccuracy
    debt_to_repay = (debt_before * frac + WAD - 1) // WAD
    assert 0 < tokens_needed == debt_to_repay - borrowed_to_remove
    profit = 1
    callback_collateral = collateral_to_remove // 3
    callback_borrowed = tokens_needed + profit
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    if different_liquidator:
        with boa.reverts("Not enough rekt"):
            controller.liquidate(borrower, borrowed_to_remove, frac, dummy_callback, calldata, sender=liquidator)
        controller.approve(liquidator, True, sender=borrower)
    with boa.reverts("Slippage"):
        controller.liquidate(borrower, borrowed_to_remove + 1, frac, dummy_callback, calldata, sender=liquidator)
    controller.liquidate(borrower, borrowed_to_remove, frac, dummy_callback, calldata, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    borrowed_to_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == pytest.approx(user_state_before[0] - collateral_to_remove, abs=3)
    assert user_state_after[1] == user_state_before[1] - borrowed_to_remove
    assert user_state_after[2] == debt_before - debt_to_repay  # partial debt repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt_to_repay
    assert controller.eval("core.repaid") == repaid + debt_to_repay
    assert dummy_callback.callback_liquidate_hits() == liquidate_hits + 1

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == debt_to_repay

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == pytest.approx(collateral_to_remove, abs=3)  # collateral tokens withdrawn from AMM
    assert liquidate_logs[0].borrowed_received == borrowed_to_remove  # Borrowed tokens withdrawn from AMM
    assert liquidate_logs[0].debt == debt_to_repay

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt_to_repay
    assert borrowed_to_liquidator == profit
    assert borrowed_from_amm == -borrowed_to_remove
    assert borrowed_from_callback == -callback_borrowed

    assert collateral_to_liquidator == callback_collateral
    assert collateral_to_callback == pytest.approx(collateral_to_remove - callback_collateral, abs=3)
    assert collateral_from_amm == pytest.approx(-collateral_to_remove, abs=3)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]


@pytest.mark.parametrize("different_liquidator", [True, False])
@pytest.mark.parametrize("frac", [25 * 10**16, 50 * 10**16, 75 * 10**16])  # 25%, 50%, 75%
def test_liquidate_partial_from_callback_unhealthy_underwater(
    controller, amm, price_oracle, borrowed_token, collateral_token, create_loan, admin, snapshot, dummy_callback, get_calldata, different_liquidator, frac, get_f_remove
):
    """
    Unhealthy and underwater partial liquidation via callback.

    Money Flow: partial_debt (callbacker) → Controller
                partial_borrowed (AMM) → Controller
                partial_COLLATERAL (callbacker, sourced from AMM) → Liquidator
                Surplus borrowed (callbacker) → Liquidator
                Position is partially liquidated
    """
    borrower = create_loan(max_debt=True)

    liquidator = borrower
    if different_liquidator:
        liquidator = boa.env.generate_address()

    # ================= Lower oracle price to make position unhealthy =================

    price_oracle.set_price(price_oracle.price() // 2, sender=admin)
    assert controller.health(borrower) < 0

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    boa.deal(borrowed_token, trader, debt // 10)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 10, 0)

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt_before = user_state_before[2]
    assert 0 < user_state_before[1] < debt_before and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")
    liquidate_hits = dummy_callback.callback_liquidate_hits()

    # ================= Calc tokens to removed from AMM =================

    f_remove = get_f_remove(frac, borrower, liquidator)
    collateral_to_remove = user_state_before[0] * f_remove // WAD
    borrowed_to_remove = user_state_before[1] * f_remove // WAD

    # ================= Setup callback tokens =================

    tokens_needed = controller.tokens_to_liquidate(borrower, frac, sender=liquidator) + 1  # Inaccuracy
    debt_to_repay = (debt_before * frac + WAD - 1) // WAD
    assert 0 < tokens_needed == debt_to_repay - borrowed_to_remove
    profit = 1
    callback_collateral = collateral_to_remove // 3
    callback_borrowed = tokens_needed + profit
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_before = snapshot(collateral_token, borrower, liquidator)

    # ================= Execute liquidation via callback =================

    with boa.reverts("Slippage"):
        controller.liquidate(borrower, borrowed_to_remove + 1, frac, dummy_callback, calldata, sender=liquidator)
    # Can liquidate unhealthy without approval
    controller.liquidate(borrower, borrowed_to_remove, frac, dummy_callback, calldata, sender=liquidator)

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    liquidate_logs = filter_logs(controller, "Liquidate")

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, liquidator)
    collateral_token_after = snapshot(collateral_token, borrower, liquidator)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = (
        borrowed_token_after["amm"] - borrowed_token_before["amm"]
    )
    borrowed_to_liquidator = (
        borrowed_token_after["liquidator"] - borrowed_token_before["liquidator"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_to_liquidator = (
        collateral_token_after["liquidator"] - collateral_token_before["liquidator"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )
    collateral_from_amm = (
        collateral_token_after["amm"] - collateral_token_before["amm"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == pytest.approx(user_state_before[0] - collateral_to_remove, abs=5)
    assert user_state_after[1] == user_state_before[1] - borrowed_to_remove
    assert user_state_after[2] == debt_before - debt_to_repay  # partial debt repaid
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - debt_to_repay
    assert controller.eval("core.repaid") == repaid + debt_to_repay
    assert dummy_callback.callback_liquidate_hits() == liquidate_hits + 1

    # ================= Verify logs =================

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == debt_to_repay

    assert len(liquidate_logs) == 1
    assert liquidate_logs[0].liquidator == liquidator
    assert liquidate_logs[0].user == borrower
    assert liquidate_logs[0].collateral_received == pytest.approx(collateral_to_remove, abs=3)  # collateral tokens withdrawn from AMM
    assert liquidate_logs[0].borrowed_received == borrowed_to_remove  # Borrowed tokens withdrawn from AMM
    assert liquidate_logs[0].debt == debt_to_repay

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt_to_repay
    assert borrowed_from_amm == -borrowed_to_remove
    assert borrowed_to_liquidator == profit
    assert borrowed_from_callback == -callback_borrowed

    assert collateral_to_liquidator == callback_collateral
    assert collateral_to_callback == pytest.approx(collateral_to_remove - callback_collateral, abs=3)
    assert collateral_from_amm == pytest.approx(-collateral_to_remove, abs=3)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_liquidator:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["borrower"] == collateral_token_before["borrower"]
