import boa
import pytest
from textwrap import dedent

from tests.utils import filter_logs, max_approve
from tests.utils.constants import ZERO_ADDRESS

COLLATERAL = 10**17
N_BANDS = 6


@pytest.fixture(scope="module", autouse=True)
def expose_internal(controller):
    controller.inject_function(
        dedent(
            """
        @external
        def repay_full(
            _for: address,
            _d_debt: uint256,
            _approval: bool,
            _xy: uint256[2],
            _cb: core.IController.CallbackData,
            _callbacker: address
        ):
            core._repay_full(_for, _d_debt, _approval, _xy, _cb, _callbacker)
        """
        )
    )


@pytest.fixture(scope="module")
def snapshot(controller, amm, fake_leverage):
    def fn(token, borrower, payer):
        return {
            "controller": token.balanceOf(controller),
            "borrower": token.balanceOf(borrower),
            "payer": token.balanceOf(payer),
            "amm": token.balanceOf(amm),
            "callback": token.balanceOf(fake_leverage),
        }

    return fn


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_full_from_wallet(
    controller, borrowed_token, collateral_token, amm, snapshot, different_payer
):
    """
    Test full repayment using only wallet tokens (no soft-liquidation).

    Money Flow: DEBT (wallet) → Controller
                xy[1] (AMM) → Borrower
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller)
    controller.create_loan(COLLATERAL, 10**18, N_BANDS)

    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert xy_before[0] == 0 and xy_before[1] > 0

    if different_payer:
        boa.deal(borrowed_token, payer, debt)

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        # xy[0] == 0, works both with and without approval
        with boa.env.anchor():
            controller.inject.repay_full(
                borrower, debt, False, xy_before, (0, 0, 0), ZERO_ADDRESS
            )
        controller.inject.repay_full(
            borrower, debt, True, xy_before, (0, 0, 0), ZERO_ADDRESS
        )

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]

    # Withdrawn from AMM
    xy = amm.get_sum_xy(borrower)
    assert amm.user_shares(borrower)[1][0] == 0
    assert xy[0] == 0
    assert xy[1] == 0

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == borrowed_to_controller
    assert repay_logs[0].collateral_decrease == collateral_to_borrower

    assert borrowed_to_controller == debt
    assert borrowed_from_payer == -debt
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_borrower == COLLATERAL
    assert collateral_from_amm == -COLLATERAL
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_full_from_xy0(
    controller, borrowed_token, collateral_token, amm, snapshot, different_payer
):
    """
    Test full repayment using only AMM soft-liquidation (xy[0] >= DEBT).

    Money Flow: xy[0] (AMM) → Controller
                xy[0] - DEBT (AMM) → Borrower (excess)
                xy[1] (AMM) → Borrower
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller)
    debt = controller.max_borrowable(COLLATERAL, N_BANDS)
    assert debt > 0
    controller.create_loan(COLLATERAL, debt, N_BANDS)

    # Push the position to SL
    trader = boa.env.generate_address()
    boa.deal(borrowed_token, trader, debt * 10_001 // 10_000)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt * 10_001 // 10_000, 0)

    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert xy_before[0] > debt and xy_before[1] > 0

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    with boa.env.prank(payer):
        with boa.reverts():
            controller.inject.repay_full(
                borrower, debt, False, xy_before, (0, 0, 0), ZERO_ADDRESS
            )
        controller.inject.repay_full(
            borrower, debt, True, xy_before, (0, 0, 0), ZERO_ADDRESS
        )

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_to_borrower = (
        borrowed_token_after["borrower"] - borrowed_token_before["borrower"]
    )
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]

    # Withdrawn from AMM
    xy_after = amm.get_sum_xy(borrower)
    assert amm.user_shares(borrower)[1][0] == 0
    assert xy_after[0] == 0
    assert xy_after[1] == 0

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == debt
    assert repay_logs[0].collateral_decrease == xy_before[1]

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -xy_before[0]
    assert borrowed_to_borrower == xy_before[0] - debt
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_borrower == xy_before[1]
    assert collateral_from_amm == -xy_before[1]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["payer"] == borrowed_token_before["payer"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_full_from_xy0_and_wallet(
    controller, borrowed_token, collateral_token, amm, snapshot, different_payer
):
    """
    Test full repayment using both AMM soft-liquidation (xy[0]) and wallet tokens.

    Money Flow: xy[0] (AMM) + (DEBT - xy[0]) (wallet) → Controller
                xy[1] (AMM) → Borrower
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller)
    debt = controller.max_borrowable(COLLATERAL, N_BANDS)
    assert debt > 0 and debt // 2 > 0
    controller.create_loan(COLLATERAL, debt, N_BANDS)

    # Push the position to SL
    trader = boa.env.generate_address()
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert 0 < xy_before[0] < debt and xy_before[1] > 0

    if different_payer:
        boa.deal(borrowed_token, payer, debt)

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        with boa.reverts():
            controller.inject.repay_full(
                borrower, debt, False, xy_before, (0, 0, 0), ZERO_ADDRESS
            )
        controller.inject.repay_full(
            borrower, debt, True, xy_before, (0, 0, 0), ZERO_ADDRESS
        )

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]

    # Withdrawn from AMM
    xy_after = amm.get_sum_xy(borrower)
    assert amm.user_shares(borrower)[1][0] == 0
    assert xy_after[0] == 0
    assert xy_after[1] == 0

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == debt
    assert repay_logs[0].collateral_decrease == xy_before[1]

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -xy_before[0]
    assert borrowed_from_payer == -(debt - xy_before[0])
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_borrower == xy_before[1]
    assert collateral_from_amm == -xy_before[1]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_full_from_callback(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    fake_leverage,
    different_payer,
):
    """
    Test full repayment using only callback tokens.

    Money Flow: cb.borrowed (callback) → Controller
                cb.borrowed - DEBT (callback) → Borrower (excess)
                cb.collateral (callback) → Borrower
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller)
    controller.create_loan(COLLATERAL, 10**18, N_BANDS)

    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert xy_before[0] == 0 and xy_before[1] > 0

    # Mock collateral withdraw from amm to callbacker and mint borrowed for callbacker
    amm.withdraw(borrower, 10**18, sender=controller.address)
    collateral_token.transfer(fake_leverage, COLLATERAL, sender=amm.address)
    boa.deal(borrowed_token, fake_leverage, debt + 1)
    cb = (amm.active_band(), debt + 1, COLLATERAL // 2)

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    with boa.env.prank(payer):
        # xy[0] == 0, works both with and without approval.
        # In practice, it can't be called without approval since repay with callback requires it.
        with boa.env.anchor():
            controller.inject.repay_full(
                borrower, debt, False, xy_before, cb, fake_leverage.address
            )
        controller.inject.repay_full(
            borrower, debt, True, xy_before, cb, fake_leverage.address
        )

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    borrowed_to_borrower = (
        borrowed_token_after["borrower"] - borrowed_token_before["borrower"]
    )
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_from_callbacker = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # Withdrawn from AMM
    xy = amm.get_sum_xy(borrower)
    assert amm.user_shares(borrower)[1][0] == 0
    assert xy[0] == 0
    assert xy[1] == 0

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == borrowed_to_controller
    assert repay_logs[0].collateral_decrease == COLLATERAL

    assert borrowed_to_controller == debt
    assert borrowed_to_borrower == 1
    assert borrowed_from_callback == -(debt + 1)
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_borrower == COLLATERAL // 2
    assert collateral_from_callbacker == -(COLLATERAL // 2)
    assert collateral_token_after["amm"] == collateral_token_before["amm"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["payer"] == borrowed_token_before["payer"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_full_from_wallet_and_callback(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    fake_leverage,
    different_payer,
):
    """
    Test full repayment using wallet + callback tokens.

    Money Flow: cb.borrowed (callback) + (DEBT - cb.borrowed) (wallet) → Controller
                cb.collateral (callback) → Borrower
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller)
    controller.create_loan(COLLATERAL, 10**18, N_BANDS)

    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert xy_before[0] == 0 and xy_before[1] > 0

    if different_payer:
        boa.deal(borrowed_token, payer, 1)

    # Mock collateral withdraw from amm to callbacker and mint borrowed for callbacker
    amm.withdraw(borrower, 10**18, sender=controller.address)
    collateral_token.transfer(fake_leverage, COLLATERAL, sender=amm.address)
    boa.deal(borrowed_token, fake_leverage, debt - 1)
    cb = (amm.active_band(), debt - 1, COLLATERAL // 2)

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        # xy[0] == 0, works both with and without approval.
        # In practice, it can't be called without approval since repay with callback requires it.
        with boa.env.anchor():
            controller.inject.repay_full(
                borrower, debt, False, xy_before, cb, fake_leverage.address
            )
        controller.inject.repay_full(
            borrower, debt, True, xy_before, cb, fake_leverage.address
        )

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_from_callbacker = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # Withdrawn from AMM
    xy = amm.get_sum_xy(borrower)
    assert amm.user_shares(borrower)[1][0] == 0
    assert xy[0] == 0
    assert xy[1] == 0

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == borrowed_to_controller
    assert repay_logs[0].collateral_decrease == COLLATERAL

    assert borrowed_to_controller == debt
    assert borrowed_from_payer == -1
    assert borrowed_from_callback == -(debt - 1)
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_borrower == COLLATERAL // 2
    assert collateral_from_callbacker == -(COLLATERAL // 2)
    assert collateral_token_after["amm"] == collateral_token_before["amm"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_full_from_xy0_and_callback(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    fake_leverage,
    different_payer,
):
    """
    Test full repayment using AMM soft-liquidation + callback tokens.

    Money Flow: xy[0] (AMM) + cb.borrowed (callback) → Controller
                xy[0] + cb.borrowed - DEBT (AMM) → Borrower (excess)
                cb.collateral (callback) → Borrower
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller)
    debt = controller.max_borrowable(COLLATERAL, N_BANDS)
    assert debt > 0
    controller.create_loan(COLLATERAL, debt, N_BANDS)

    # Push the position to SL
    trader = boa.env.generate_address()
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert 1 < xy_before[0] < debt and xy_before[1] > 0

    # Mock collateral withdraw from amm to callbacker and mint borrowed for callbacker
    amm.withdraw(borrower, 10**18, sender=controller.address)
    collateral_token.transfer(fake_leverage, xy_before[1], sender=amm.address)
    boa.deal(borrowed_token, fake_leverage, debt - 1)
    cb = (amm.active_band(), debt - 1, xy_before[1] // 2)

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    with boa.env.prank(payer):
        # xy[0] == 0, works both with and without approval.
        # In practice, it can't be called without approval since repay with callback requires it.
        with boa.reverts():
            controller.inject.repay_full(
                borrower, debt, False, xy_before, cb, fake_leverage.address
            )
        controller.inject.repay_full(
            borrower, debt, True, xy_before, cb, fake_leverage.address
        )

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    borrowed_to_borrower = (
        borrowed_token_after["borrower"] - borrowed_token_before["borrower"]
    )
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_from_callbacker = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # Withdrawn from AMM
    xy = amm.get_sum_xy(borrower)
    assert amm.user_shares(borrower)[1][0] == 0
    assert xy[0] == 0
    assert xy[1] == 0

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == borrowed_to_controller
    assert repay_logs[0].collateral_decrease == xy_before[1]

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -xy_before[0]
    assert borrowed_from_callback == -(debt - 1)
    assert borrowed_to_borrower == xy_before[0] - 1

    assert collateral_to_borrower == xy_before[1] // 2
    assert collateral_from_callbacker == -(xy_before[1] // 2)
    assert collateral_token_after["amm"] == collateral_token_before["amm"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["payer"] == borrowed_token_before["payer"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_full_from_wallet_and_y0_and_callback(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    fake_leverage,
    different_payer,
):
    """
    Test full repayment using all three sources: AMM + wallet + callback.

    Money Flow: xy[0] (AMM) + cb.borrowed (callback) + (DEBT - xy[0] - cb.borrowed) (wallet) → Controller
                cb.collateral (callback) → Borrower
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller)
    debt = controller.max_borrowable(COLLATERAL, N_BANDS)
    assert debt > 0
    controller.create_loan(COLLATERAL, debt, N_BANDS)

    # Push the position to SL
    trader = boa.env.generate_address()
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert 1 < xy_before[0] < debt and xy_before[1] > 0

    if different_payer:
        boa.deal(borrowed_token, payer, 1)

    # Mock collateral withdraw from amm to callbacker and mint borrowed for callbacker
    amm.withdraw(borrower, 10**18, sender=controller.address)
    collateral_token.transfer(fake_leverage, xy_before[1], sender=amm.address)
    boa.deal(borrowed_token, fake_leverage, debt - xy_before[0] - 1)
    cb = (amm.active_band(), debt - xy_before[0] - 1, xy_before[1] // 2)

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        # xy[0] == 0, works both with and without approval.
        # In practice, it can't be called without approval since repay with callback requires it.
        with boa.reverts():
            controller.inject.repay_full(
                borrower, debt, False, xy_before, cb, fake_leverage.address
            )
        controller.inject.repay_full(
            borrower, debt, True, xy_before, cb, fake_leverage.address
        )

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_from_callbacker = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # Withdrawn from AMM
    xy = amm.get_sum_xy(borrower)
    assert amm.user_shares(borrower)[1][0] == 0
    assert xy[0] == 0
    assert xy[1] == 0

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == 0
    assert state_logs[0].debt == 0
    assert state_logs[0].n1 == 0
    assert state_logs[0].n2 == 0
    assert state_logs[0].liquidation_discount == 0

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == borrowed_to_controller
    assert repay_logs[0].collateral_decrease == xy_before[1]

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -xy_before[0]
    assert borrowed_from_callback == -(debt - xy_before[0] - 1)
    assert borrowed_from_payer == -1

    assert collateral_to_borrower == xy_before[1] // 2
    assert collateral_from_callbacker == -(xy_before[1] // 2)
    assert collateral_token_after["amm"] == collateral_token_before["amm"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]
