import pytest
import boa
from eth_abi import encode

from tests.utils import max_approve
from tests.utils.constants import MAX_UINT256, ZERO_ADDRESS

N_BANDS = 6


@pytest.fixture(scope="module")
def collateral_amount(collateral_token):
    return int(N_BANDS * 0.05 * 10 ** collateral_token.decimals())


@pytest.fixture(scope="module")
def create_loan(controller, collateral_token, borrowed_token, collateral_amount):
    def fn(max_debt=False):
        borrower = boa.env.eoa
        boa.deal(collateral_token, borrower, collateral_amount)
        max_approve(collateral_token, controller)
        max_approve(borrowed_token, controller)
        debt = 10 ** borrowed_token.decimals()
        if max_debt:
            debt = controller.max_borrowable(collateral_amount, N_BANDS)
        controller.create_loan(collateral_amount, debt, N_BANDS)
        assert debt == controller.debt(borrower)
        return borrower

    return fn


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
    def fn(token, borrower, payer):
        return {
            "borrower": token.balanceOf(borrower),
            "payer": token.balanceOf(payer),
            "controller": token.balanceOf(controller),
            "amm": token.balanceOf(amm),
            "callback": token.balanceOf(dummy_callback),
        }

    return fn


@pytest.mark.parametrize("different_payer", [True, False])
def test_full_repay_from_wallet(
    controller,
    borrowed_token,
    collateral_token,
    create_loan,
    snapshot,
    collateral_amount,
    different_payer,
):
    """
    Test full repayment using wallet tokens.

    Money Flow: debt (payer) → Controller
                COLLATERAL (AMM) → Borrower
                Position is fully closed
    """
    borrower = create_loan()

    payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup payer tokens =================

    if different_payer:
        boa.deal(borrowed_token, payer, debt)
        max_approve(borrowed_token, controller, sender=payer)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute full repayment =================

    controller.repay(MAX_UINT256, borrower, sender=payer)

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # collateral in AMM
    assert user_state_after[1] == 0  # borrowed in AMM
    assert user_state_after[2] == 0  # debt
    assert user_state_after[3] == 0  # N == 0
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_payer == -debt
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_borrower == collateral_amount
    assert collateral_from_amm == -collateral_amount
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_full_repay_from_callback(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    dummy_callback,
    get_calldata,
    snapshot,
    collateral_amount,
    different_payer,
):
    """
    Test full repayment using callback tokens.

    Money Flow: callback_borrowed (callback) → Controller
                callback_borrowed - debt (callback) → Borrower (excess)
                COLLATERAL (AMM) → Callback → Borrower (excess)
                Position is fully closed
    """
    borrower = create_loan()

    payer = borrower
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup callback tokens =================

    callback_borrowed = debt + 1
    callback_collateral = collateral_amount // 2
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)
    repay_hits = dummy_callback.callback_repay_hits()

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute full repayment =================

    if different_payer:
        # Repay with callback reverts without approval
        with boa.reverts():
            controller.repay(
                0, borrower, amm.active_band(), dummy_callback, calldata, sender=payer
            )
        controller.approve(payer, True, sender=borrower)
    controller.repay(
        0, borrower, amm.active_band(), dummy_callback, calldata, sender=payer
    )

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_to_borrower = (
        borrowed_token_after["borrower"] - borrowed_token_before["borrower"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # collateral in AMM
    assert user_state_after[1] == 0  # borrowed in AMM
    assert user_state_after[2] == 0  # debt
    assert user_state_after[3] == 0  # N == 0
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt
    assert dummy_callback.callback_repay_hits() == repay_hits + 1

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_to_borrower == 1
    assert borrowed_from_callback == -(debt + 1)
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_borrower == collateral_amount // 2
    assert collateral_to_callback == collateral_amount // 2
    assert collateral_from_amm == -collateral_amount
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["payer"] == borrowed_token_before["payer"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_full_repay_from_xy0(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    snapshot,
    different_payer,
):
    """
    Test full repayment when position is in soft-liquidation (underwater).

    Money Flow: xy[0] (AMM) → Controller
                xy[0] - debt (Controller) → Borrower (excess)
                xy[1] (AMM) → Borrower
                Position is fully closed
    """
    borrower = create_loan(max_debt=True)

    payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Push position to soft-liquidation =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt * 10_001 // 10_000)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt * 10_001 // 10_000, 0)

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert user_state_before[1] > debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute full repayment =================

    if different_payer:
        # Repay with xy0 reverts without approval
        with boa.reverts():
            controller.repay(MAX_UINT256, borrower, sender=payer)
        controller.approve(payer, True, sender=borrower)
    controller.repay(MAX_UINT256, borrower, sender=payer)

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]
    borrowed_to_borrower = (
        borrowed_token_after["borrower"] - borrowed_token_before["borrower"]
    )
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # collateral in AMM
    assert user_state_after[1] == 0  # borrowed in AMM
    assert user_state_after[2] == 0  # debt
    assert user_state_after[3] == 0  # N == 0
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_to_borrower == user_state_before[1] - debt
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_borrower == user_state_before[0]
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["payer"] == borrowed_token_before["payer"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_full_repay_from_wallet_and_callback(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    dummy_callback,
    get_calldata,
    snapshot,
    collateral_amount,
    different_payer,
):
    """
    Test full repayment using both wallet and callback tokens.

    Money Flow: callback_borrowed (callback) + (debt - callback_borrowed) (wallet) → Controller
                COLLATERAL (AMM) → Callback → Borrower (excess)
                Position is fully closed
    """
    borrower = create_loan()

    payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup callback tokens =================

    callback_borrowed = debt - 1
    callback_collateral = collateral_amount // 2
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)
    repay_hits = dummy_callback.callback_repay_hits()

    # ================= Setup payer tokens =================

    if different_payer:
        boa.deal(borrowed_token, payer, 1)
        max_approve(borrowed_token, controller, sender=payer)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute full repayment =================

    if different_payer:
        # Repay with callback reverts without approval
        with boa.reverts():
            controller.repay(
                MAX_UINT256,
                borrower,
                amm.active_band(),
                dummy_callback,
                calldata,
                sender=payer,
            )
        controller.approve(payer, True, sender=borrower)
    controller.repay(
        MAX_UINT256, borrower, amm.active_band(), dummy_callback, calldata, sender=payer
    )

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # collateral in AMM
    assert user_state_after[1] == 0  # borrowed in AMM
    assert user_state_after[2] == 0  # debt
    assert user_state_after[3] == 0  # N == 0
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt
    assert dummy_callback.callback_repay_hits() == repay_hits + 1

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_from_payer == -1
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_borrower == collateral_amount - callback_collateral
    assert collateral_to_callback == callback_collateral
    assert collateral_from_amm == -collateral_amount
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_full_repay_from_xy0_and_wallet(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    snapshot,
    different_payer,
):
    """
    Test full repayment when position is underwater using AMM + wallet tokens.

    Money Flow: xy[0] (AMM) + (debt - xy[0]) (wallet) → Controller
                xy[1] (AMM) → Borrower
                Position is fully closed
    """
    borrower = create_loan(max_debt=True)

    payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Push position to soft-liquidation =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup payer tokens =================

    if different_payer:
        boa.deal(borrowed_token, payer, debt - user_state_before[1])
        max_approve(borrowed_token, controller, sender=payer)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute full repayment =================

    if different_payer:
        # Repay with xy0 reverts without approval
        with boa.reverts():
            controller.repay(MAX_UINT256, borrower, sender=payer)
        controller.approve(payer, True, sender=borrower)
    controller.repay(MAX_UINT256, borrower, sender=payer)

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # collateral in AMM
    assert user_state_after[1] == 0  # borrowed in AMM
    assert user_state_after[2] == 0  # debt
    assert user_state_after[3] == 0  # N == 0
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_from_payer == -(debt - user_state_before[1])
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_borrower == user_state_before[0]
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_full_repay_from_xy0_and_callback(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    dummy_callback,
    get_calldata,
    snapshot,
    different_payer,
):
    """
    Test full repayment when position is underwater using AMM + callback tokens.

    Money Flow: xy[0] (AMM) + callback_borrowed (callback) → Controller
                xy[0] + callback_borrowed - debt (AMM) → Borrower (excess)
                xy[1] (AMM) → Callback → Borrower (excess)
                Position is fully closed
    """
    borrower = create_loan(max_debt=True)

    payer = borrower
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Push position to soft-liquidation =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup callback tokens =================

    callback_borrowed = debt - user_state_before[1] + 1
    callback_collateral = user_state_before[0] // 3
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)
    repay_hits = dummy_callback.callback_repay_hits()

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute full repayment =================

    if different_payer:
        # Repay with callback reverts without approval
        with boa.reverts():
            controller.repay(
                0, borrower, amm.active_band(), dummy_callback, calldata, sender=payer
            )
        controller.approve(payer, True, sender=borrower)
    controller.repay(
        0, borrower, amm.active_band(), dummy_callback, calldata, sender=payer
    )

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

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
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # collateral in AMM
    assert user_state_after[1] == 0  # borrowed in AMM
    assert user_state_after[2] == 0  # debt
    assert user_state_after[3] == 0  # N == 0
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt
    assert dummy_callback.callback_repay_hits() == repay_hits + 1

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_to_borrower == 1

    assert collateral_to_borrower == callback_collateral
    assert collateral_to_callback == user_state_before[0] - callback_collateral
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["payer"] == borrowed_token_before["payer"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_full_repay_from_xy0_and_wallet_and_callback(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    dummy_callback,
    get_calldata,
    snapshot,
    different_payer,
):
    """
    Test full repayment when position is underwater using all three sources: AMM + wallet + callback.

    Money Flow: xy[0] (AMM) + callback_borrowed (callback) + (debt - xy[0] - callback_borrowed) (wallet) → Controller
                xy[1] (AMM) → Callback → Borrower (excess)
                Position is fully closed
    """
    borrower = create_loan(max_debt=True)

    payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Push position to soft-liquidation =================

    trader = boa.env.generate_address()
    debt = controller.debt(borrower)
    assert debt > 0
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup callback tokens =================

    callback_borrowed = debt - user_state_before[1] - 1
    callback_collateral = user_state_before[0] // 3
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)
    repay_hits = dummy_callback.callback_repay_hits()

    # ================= Setup payer tokens =================

    if different_payer:
        boa.deal(borrowed_token, payer, debt - user_state_before[1] - callback_borrowed)
        max_approve(borrowed_token, controller, sender=payer)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute full repayment =================

    if different_payer:
        # Repay with callback reverts without approval
        with boa.reverts():
            controller.repay(
                MAX_UINT256,
                borrower,
                amm.active_band(),
                dummy_callback,
                calldata,
                sender=payer,
            )
        controller.approve(payer, True, sender=borrower)
    controller.repay(
        MAX_UINT256, borrower, amm.active_band(), dummy_callback, calldata, sender=payer
    )

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_borrower = (
        collateral_token_after["borrower"] - collateral_token_before["borrower"]
    )
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == 0  # collateral in AMM
    assert user_state_after[1] == 0  # borrowed in AMM
    assert user_state_after[2] == 0  # debt
    assert user_state_after[3] == 0  # N == 0
    assert controller.total_debt() == total_debt - debt
    assert controller.eval("core.repaid") == repaid + debt
    assert dummy_callback.callback_repay_hits() == repay_hits + 1

    # ================= Verify money flows =================

    assert borrowed_to_controller == debt
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_from_payer == -1

    assert collateral_to_borrower == callback_collateral
    assert collateral_to_callback == user_state_before[0] - callback_collateral
    assert collateral_from_amm == -user_state_before[0]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
@pytest.mark.parametrize("approval", [True, False])
def test_partial_repay_from_wallet(
    controller,
    borrowed_token,
    collateral_token,
    create_loan,
    snapshot,
    admin,
    different_payer,
    approval,
):
    """
    Test partial repayment using wallet tokens.

    Money Flow: wallet_borrowed (payer) → Controller
                Position remains active with reduced debt
    """
    borrower = create_loan()

    payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Set new liquidation discount =================

    old_liquidation_discount = controller.liquidation_discount()
    new_liquidation_discount = old_liquidation_discount // 2
    controller.set_borrowing_discounts(
        controller.loan_discount(), new_liquidation_discount, sender=admin
    )

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    wallet_borrowed = debt // 2
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup payer tokens =================

    if different_payer:
        boa.deal(borrowed_token, payer, wallet_borrowed)
        max_approve(borrowed_token, controller, sender=payer)

    # ================= Calculate future health =================

    # Approved caller triggers borrower's liquidation discount update which affects health
    if different_payer and approval:
        controller.approve(payer, True, sender=borrower)

    d_collateral = 0
    d_debt = wallet_borrowed
    preview_health = controller.repay_health_preview(
        d_collateral, d_debt, borrower, payer, False, False
    )
    preview_health_full = controller.repay_health_preview(
        d_collateral, d_debt, borrower, payer, False, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    controller.repay(wallet_borrowed, borrower, sender=payer)

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == user_state_before[0]  # collateral in AMM
    assert user_state_after[1] == user_state_before[1]  # borrowed in AMM
    assert user_state_after[2] == debt - wallet_borrowed  # debt
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - wallet_borrowed
    assert controller.eval("core.repaid") == repaid + wallet_borrowed
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )

    # ================= Verify money flows =================

    assert borrowed_to_controller == wallet_borrowed
    assert borrowed_from_payer == -wallet_borrowed
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]
    assert collateral_token_after["amm"] == collateral_token_before["amm"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_partial_repay_from_callback(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    dummy_callback,
    get_calldata,
    snapshot,
    collateral_amount,
    different_payer,
):
    """
    Test partial repayment using callback tokens.

    Money Flow: callback_borrowed (callback) → Controller
                xy[0] (AMM) -> Callback callback_collateral → AMM (remaining)
                Position remains active with reduced debt
    """
    borrower = create_loan()

    payer = borrower
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    callback_borrowed = debt // 3
    callback_collateral = collateral_amount * 3 // 4
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup callback tokens =================

    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)
    repay_hits = dummy_callback.callback_repay_hits()

    # ================= Calculate future health =================

    d_collateral = collateral_amount - callback_collateral
    d_debt = callback_borrowed
    # Approval is required to use callback,
    # so we do calculation assuming that approval is going to be given.
    preview_health = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, False, False
    )
    preview_health_full = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, False, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    if different_payer:
        # Repay with callback reverts without approval
        with boa.reverts():
            controller.repay(
                0, borrower, amm.active_band(), dummy_callback, calldata, sender=payer
            )
        controller.approve(payer, True, sender=borrower)
    controller.repay(
        0, borrower, amm.active_band(), dummy_callback, calldata, sender=payer
    )

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == callback_collateral  # collateral in AMM
    assert user_state_after[1] == user_state_before[1]  # borrowed in AMM
    assert user_state_after[2] == debt - callback_borrowed  # debt
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - callback_borrowed
    assert controller.eval("core.repaid") == repaid + callback_borrowed
    assert dummy_callback.callback_repay_hits() == repay_hits + 1
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )

    # ================= Verify money flows =================

    assert borrowed_to_controller == callback_borrowed
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]

    assert collateral_to_callback == collateral_amount - callback_collateral
    assert collateral_from_amm == -(collateral_amount - callback_collateral)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]

    if different_payer:
        assert borrowed_token_after["payer"] == borrowed_token_before["payer"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_partial_repay_from_wallet_and_callback(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    dummy_callback,
    get_calldata,
    snapshot,
    collateral_amount,
    different_payer,
):
    """
    Test partial repayment using both wallet and callback tokens.

    Money Flow: wallet_borrowed (wallet) + callback_borrowed (callback) → Controller
                callback_collateral (callback) → AMM (remaining)
                Position remains active with reduced debt
    """
    borrower = create_loan()

    payer = borrower
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    wallet_borrowed = debt // 3  # Wallet provides 1/3 of debt
    callback_borrowed = debt // 3  # Callback provides 1/3 of debt
    callback_collateral = (
        collateral_amount * 2 // 3
    )  # Callback provides 2/3 of collateral
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup payer tokens =================

    if different_payer:
        boa.deal(borrowed_token, payer, wallet_borrowed)
        max_approve(borrowed_token, controller, sender=payer)

    # ================= Setup callback tokens =================

    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)
    repay_hits = dummy_callback.callback_repay_hits()

    # ================= Calculate future health =================

    d_collateral = user_state_before[0] - callback_collateral
    d_debt = wallet_borrowed + callback_borrowed
    # Approval is required to use callback,
    # so we do calculation assuming that approval is going to be given.
    preview_health = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, False, False
    )
    preview_health_full = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, False, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    if different_payer:
        # Repay with callback reverts without approval
        with boa.reverts():
            controller.repay(
                wallet_borrowed,
                borrower,
                amm.active_band(),
                dummy_callback,
                calldata,
                sender=payer,
            )
        controller.approve(payer, True, sender=borrower)

    controller.repay(
        wallet_borrowed,
        borrower,
        amm.active_band(),
        dummy_callback,
        calldata,
        sender=payer,
    )

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == callback_collateral  # collateral in AMM
    assert user_state_after[1] == user_state_before[1]  # borrowed in AMM
    assert user_state_after[2] == debt - wallet_borrowed - callback_borrowed  # debt
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - wallet_borrowed - callback_borrowed
    assert (
        controller.eval("core.repaid") == repaid + wallet_borrowed + callback_borrowed
    )
    assert dummy_callback.callback_repay_hits() == repay_hits + 1
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )

    # ================= Verify money flows =================

    assert borrowed_to_controller == wallet_borrowed + callback_borrowed
    assert borrowed_from_payer == -wallet_borrowed
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_callback == collateral_amount - callback_collateral
    assert collateral_from_amm == -(collateral_amount - callback_collateral)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
@pytest.mark.parametrize("approval", [True, False])
def test_partial_repay_from_wallet_underwater(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    snapshot,
    admin,
    different_payer,
    approval,
):
    """
    Test partial repayment from wallet when position is underwater (soft-liquidated).

    Money Flow: wallet_borrowed (wallet) → Controller
                Position remains underwater (no collateral return)
    """
    borrower = create_loan(max_debt=True)

    payer = borrower
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Push position to underwater =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert debt > 0
    trader = boa.env.generate_address()
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Set new liquidation discount =================

    old_liquidation_discount = controller.liquidation_discount()
    new_liquidation_discount = old_liquidation_discount // 2
    controller.set_borrowing_discounts(
        controller.loan_discount(), new_liquidation_discount, sender=admin
    )

    # ================= Setup payer tokens =================

    wallet_borrowed = debt // 3  # Repay 1/3 of the debt
    if different_payer:
        boa.deal(borrowed_token, payer, wallet_borrowed)
        max_approve(borrowed_token, controller, sender=payer)

    # ================= Calculate future health =================

    # Approved caller triggers borrower's liquidation discount update which affects health
    if different_payer and approval:
        controller.approve(payer, True, sender=borrower)

    d_collateral = 0
    d_debt = wallet_borrowed
    preview_health = controller.repay_health_preview(
        d_collateral, d_debt, borrower, payer, False, False
    )
    preview_health_full = controller.repay_health_preview(
        d_collateral, d_debt, borrower, payer, False, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    controller.repay(wallet_borrowed, borrower, amm.active_band(), sender=payer)

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == user_state_before[0]  # collateral in AMM unchanged
    assert user_state_after[1] == user_state_before[1]  # borrowed in AMM unchanged
    assert user_state_after[2] == debt - wallet_borrowed  # debt reduced
    assert user_state_after[3] == user_state_before[3]  # N unchanged
    assert controller.total_debt() == total_debt - wallet_borrowed
    assert controller.eval("core.repaid") == repaid + wallet_borrowed
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )

    # ================= Verify money flows =================

    assert borrowed_to_controller == wallet_borrowed
    assert borrowed_from_payer == -wallet_borrowed
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]
    assert collateral_token_after["amm"] == collateral_token_before["amm"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_partial_repay_from_xy0_underwater_shrink(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    snapshot,
    different_payer,
):
    """
    Test partial repayment from xy[0] when position is underwater (soft-liquidated) with shrink.

    Money Flow: xy[0] (AMM) → Controller
                Position exits from underwater (no collateral return though)
    """
    borrower = create_loan(max_debt=True)

    payer = borrower
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Push position to underwater =================

    # 6, 5, 4, 3 ticks in collateral
    # 2 tick active
    # 1 tick in borrowed
    trader = boa.env.generate_address()
    ticks_before = amm.read_user_tick_numbers(borrower)
    assert ticks_before[1] - ticks_before[0] == 5
    amount_out = amm.bands_y(ticks_before[0]) + amm.bands_y(ticks_before[0] + 1) // 2
    amount_out = amount_out // 10 ** (18 - collateral_token.decimals())
    amount_in = amm.get_dx(0, 1, amount_out)
    boa.deal(borrowed_token, trader, amount_in)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange_dy(0, 1, amount_out, amount_in + 1)

    # ================= Get tokens_to_shrink =================

    assert controller.tokens_to_shrink(borrower) == 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Calculate future health =================

    d_collateral = 0
    d_debt = 0
    # Approval is required to shrink,
    # so we do calculation assuming that approval is going to be given.
    preview_health = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, True, False
    )
    preview_health_full = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, True, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    if different_payer:
        # Repay reverts without approval
        with boa.reverts():
            controller.repay(
                0, borrower, amm.active_band(), ZERO_ADDRESS, b"", True, sender=payer
            )
        controller.approve(payer, True, sender=borrower)

    controller.repay(
        0, borrower, amm.active_band(), ZERO_ADDRESS, b"", True, sender=payer
    )

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == user_state_before[0]  # collateral in AMM unchanged
    assert user_state_after[1] == 0  # no borrowed tokens in AMM (exited underwater)
    assert user_state_after[2] == debt - user_state_before[1]  # debt reduced by xy[0]
    assert user_state_after[3] == user_state_before[3] - 2  # N shrunk by 2
    assert controller.total_debt() == total_debt - user_state_before[1]
    assert controller.eval("core.repaid") == repaid + user_state_before[1]
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )

    # ================= Verify money flows =================

    assert borrowed_to_controller == user_state_before[1]
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_token_after["payer"] == borrowed_token_before["payer"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]
    assert collateral_token_after["amm"] == collateral_token_before["amm"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_partial_repay_from_xy0_and_wallet_underwater_shrink(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    snapshot,
    different_payer,
):
    """
    Test partial repayment from xy[0] + wallet when position is underwater (soft-liquidated) with shrink.

    Money Flow: xy[0] (AMM) + wallet_borrowed (wallet) → Controller
                Position exits from underwater (no collateral return though)
    """
    borrower = create_loan(max_debt=True)

    payer = borrower
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Push position to underwater =================

    # 6, 5, 4, 3, 2 ticks in collateral
    # 1 tick active
    trader = boa.env.generate_address()
    ticks_before = amm.read_user_tick_numbers(borrower)
    assert ticks_before[1] - ticks_before[0] == 5
    amount_out = (
        amm.bands_y(ticks_before[0]) // 100 // 10 ** (18 - collateral_token.decimals())
    )  # 1 / 100
    amount_out = max(amount_out, 1)
    boa.deal(borrowed_token, trader, amm.get_dx(0, 1, amount_out))
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange_dy(0, 1, amount_out, 2**256 - 1)
    assert controller.user_state(borrower)[1] > 0

    # ================= Get tokens_to_shrink =================

    tokens_to_shrink = controller.tokens_to_shrink(borrower)
    assert tokens_to_shrink > 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup payer tokens =================

    wallet_borrowed = tokens_to_shrink  # Additional wallet repayment
    if different_payer:
        boa.deal(borrowed_token, payer, wallet_borrowed)
        max_approve(borrowed_token, controller, sender=payer)

    # ================= Calculate future health =================

    d_collateral = 0
    d_debt = wallet_borrowed
    # Approval is required to shrink,
    # so we do calculation assuming that approval is going to be given.
    preview_health = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, True, False
    )
    preview_health_full = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, True, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    if different_payer:
        # Repay reverts without approval
        with boa.reverts():
            controller.repay(
                wallet_borrowed,
                borrower,
                amm.active_band(),
                ZERO_ADDRESS,
                b"",
                True,
                sender=payer,
            )
        controller.approve(payer, True, sender=borrower)
    controller.repay(
        wallet_borrowed,
        borrower,
        amm.active_band(),
        ZERO_ADDRESS,
        b"",
        True,
        sender=payer,
    )

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == user_state_before[0]  # collateral in AMM unchanged
    assert user_state_after[1] == 0  # no borrowed tokens in AMM (exited underwater)
    assert (
        user_state_after[2] == debt - user_state_before[1] - wallet_borrowed
    )  # debt reduced
    assert user_state_after[3] == user_state_before[3] - 1  # N shrunk by 1
    assert (
        controller.total_debt() == total_debt - user_state_before[1] - wallet_borrowed
    )
    assert (
        controller.eval("core.repaid")
        == repaid + user_state_before[1] + wallet_borrowed
    )
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )

    # ================= Verify money flows =================

    assert borrowed_to_controller == user_state_before[1] + wallet_borrowed
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_from_payer == -wallet_borrowed
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]
    assert collateral_token_after["amm"] == collateral_token_before["amm"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_partial_repay_from_xy0_and_callback_underwater_shrink(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    dummy_callback,
    get_calldata,
    snapshot,
    different_payer,
):
    """
    Test partial repayment from xy[0] + callback when position is underwater (soft-liquidated) with shrink.

    Money Flow: xy[0] (AMM) + callback_borrowed (callback) → Controller
                callback_collateral (callback) → AMM (remaining)
                Position exits from underwater
    """
    borrower = create_loan(max_debt=True)

    payer = borrower
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Push position to underwater =================

    # 6, 5, 4, 3, 2 ticks in collateral
    # 1 tick active
    trader = boa.env.generate_address()
    ticks_before = amm.read_user_tick_numbers(borrower)
    assert ticks_before[1] - ticks_before[0] == 5
    amount_out = (
        amm.bands_y(ticks_before[0]) // 100 // 10 ** (18 - collateral_token.decimals())
    )  # 1 / 100
    amount_out = max(amount_out, 1)
    boa.deal(borrowed_token, trader, amm.get_dx(0, 1, amount_out))
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange_dy(0, 1, amount_out, 2**256 - 1)
    assert controller.user_state(borrower)[1] > 0

    # ================= Get tokens_to_shrink =================

    d_collateral = 2  # The amount of user's position collateral to be used by callback
    tokens_to_shrink = controller.tokens_to_shrink(borrower, d_collateral)
    assert tokens_to_shrink > 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup callback tokens =================

    callback_borrowed = tokens_to_shrink  # Additional callback repayment
    callback_collateral = (
        user_state_before[0] - d_collateral
    )  # Some collateral from callback
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)
    repay_hits = dummy_callback.callback_repay_hits()

    # ================= Calculate future health =================

    d_collateral = user_state_before[0] - callback_collateral
    d_debt = callback_borrowed
    # Approval is required to use callback and shrink,
    # so we do calculation assuming that approval is going to be given.
    preview_health = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, True, False
    )
    preview_health_full = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, True, True
    )

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    if different_payer:
        # Repay reverts without approval
        with boa.reverts():
            controller.repay(
                0,
                borrower,
                amm.active_band(),
                dummy_callback,
                calldata,
                True,
                sender=payer,
            )
        controller.approve(payer, True, sender=borrower)

    controller.repay(
        0, borrower, amm.active_band(), dummy_callback, calldata, True, sender=payer
    )

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == callback_collateral  # collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM (exited underwater)
    assert (
        user_state_after[2] == debt - user_state_before[1] - callback_borrowed
    )  # debt reduced
    assert user_state_after[3] == user_state_before[3] - 1  # N shrunk by 1
    assert (
        controller.total_debt() == total_debt - user_state_before[1] - callback_borrowed
    )
    assert (
        controller.eval("core.repaid")
        == repaid + user_state_before[1] + callback_borrowed
    )
    assert dummy_callback.callback_repay_hits() == repay_hits + 1
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )

    # ================= Verify money flows =================

    assert borrowed_to_controller == user_state_before[1] + callback_borrowed
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_token_after["payer"] == borrowed_token_before["payer"]

    assert collateral_to_callback == user_state_before[0] - callback_collateral
    assert collateral_from_amm == -(user_state_before[0] - callback_collateral)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_partial_repay_from_xy0_and_wallet_and_callback_underwater_shrink(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    dummy_callback,
    get_calldata,
    snapshot,
    different_payer,
):
    """
    Test partial repayment from xy[0] + wallet + callback when position is underwater (soft-liquidated) with shrink.

    Money Flow: xy[0] (AMM) + wallet_borrowed (wallet) + callback_borrowed (callback) → Controller
                callback_collateral (callback) → AMM (remaining)
                Position exits from underwater
    """
    borrower = create_loan(max_debt=True)

    payer = borrower
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Push position to underwater =================

    # 6, 5, 4, 3, 2 ticks in collateral
    # 1 tick active
    trader = boa.env.generate_address()
    ticks_before = amm.read_user_tick_numbers(borrower)
    assert ticks_before[1] - ticks_before[0] == 5
    amount_out = (
        amm.bands_y(ticks_before[0]) // 100 // 10 ** (18 - collateral_token.decimals())
    )  # 1 / 100
    amount_out = max(amount_out, 1)
    boa.deal(borrowed_token, trader, amm.get_dx(0, 1, amount_out))
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange_dy(0, 1, amount_out, 2**256 - 1)
    assert controller.user_state(borrower)[1] > 0

    # ================= Get tokens_to_shrink =================

    d_collateral = 2  # The amount of user's position collateral to be used by callback
    tokens_to_shrink = controller.tokens_to_shrink(borrower, d_collateral)
    assert tokens_to_shrink > 0

    # ================= Capture initial state =================

    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert 0 < user_state_before[1] < debt and user_state_before[0] > 0
    total_debt = controller.total_debt()
    repaid = controller.eval("core.repaid")

    # ================= Setup payer tokens =================

    wallet_borrowed = tokens_to_shrink // 3  # Wallet provides 1/6 of debt
    if different_payer:
        boa.deal(borrowed_token, payer, wallet_borrowed)
        max_approve(borrowed_token, controller, sender=payer)

    # ================= Setup callback tokens =================

    callback_borrowed = (
        tokens_to_shrink - wallet_borrowed
    )  # Callback provides 1/6 of debt
    callback_collateral = (
        user_state_before[0] - d_collateral
    )  # Some collateral from callback
    calldata = get_calldata(callback_borrowed, callback_collateral)
    boa.deal(borrowed_token, dummy_callback, callback_borrowed)
    repay_hits = dummy_callback.callback_repay_hits()

    # ================= Calculate future health =================

    d_collateral = user_state_before[0] - callback_collateral
    d_debt = wallet_borrowed + callback_borrowed
    # Approval is required to use callback and shrink,
    # so we do calculation assuming that approval is going to be given.
    preview_health = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, True, False
    )
    preview_health_full = controller.repay_health_preview(
        d_collateral, d_debt, borrower, borrower, True, True
    )
    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    if different_payer:
        # Repay reverts without approval
        with boa.reverts():
            controller.repay(
                wallet_borrowed,
                borrower,
                amm.active_band(),
                dummy_callback,
                calldata,
                True,
                sender=payer,
            )
        controller.approve(payer, True, sender=borrower)

    controller.repay(
        wallet_borrowed,
        borrower,
        amm.active_band(),
        dummy_callback,
        calldata,
        True,
        sender=payer,
    )

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]
    borrowed_from_callback = (
        borrowed_token_after["callback"] - borrowed_token_before["callback"]
    )
    collateral_from_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_to_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    user_state_after = controller.user_state(borrower)
    assert user_state_after[0] == callback_collateral  # collateral in AMM
    assert user_state_after[1] == 0  # no borrowed tokens in AMM (exited underwater)
    assert (
        user_state_after[2]
        == debt - user_state_before[1] - wallet_borrowed - callback_borrowed
    )  # debt reduced
    assert user_state_after[3] == user_state_before[3] - 1  # N shrunk by 1
    assert (
        controller.total_debt()
        == total_debt - user_state_before[1] - wallet_borrowed - callback_borrowed
    )
    assert (
        controller.eval("core.repaid")
        == repaid + user_state_before[1] + wallet_borrowed + callback_borrowed
    )
    assert dummy_callback.callback_repay_hits() == repay_hits + 1
    assert controller.health(borrower) == pytest.approx(preview_health, rel=1e-10)
    assert controller.health(borrower, True) == pytest.approx(
        preview_health_full, rel=1e-10
    )

    # ================= Verify money flows =================

    assert (
        borrowed_to_controller
        == user_state_before[1] + wallet_borrowed + callback_borrowed
    )
    assert borrowed_from_payer == -wallet_borrowed
    assert borrowed_from_amm == -user_state_before[1]
    assert borrowed_from_callback == -callback_borrowed

    assert collateral_to_callback == user_state_before[0] - callback_collateral
    assert collateral_from_amm == -(user_state_before[0] - callback_collateral)
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_partial_repay_cannot_shrink(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    create_loan,
    snapshot,
    different_payer,
):
    """
    Test that attempt to shrink the position to less than 4 bands reverts with "Can't shrink" error.
    """
    borrower = create_loan(max_debt=True)

    payer = borrower
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Push position to underwater =================

    # 6, 5, 4 ticks in collateral
    # 3 tick active
    # 2, 1 tick in borrowed
    trader = boa.env.generate_address()
    ticks_before = amm.read_user_tick_numbers(borrower)
    assert ticks_before[1] - ticks_before[0] == 5
    amount_out = (
        amm.bands_y(ticks_before[0])
        + amm.bands_y(ticks_before[0] + 1)
        + amm.bands_y(ticks_before[0] + 2) // 2
    )
    amount_out = amount_out // 10 ** (18 - collateral_token.decimals())
    amount_in = amm.get_dx(0, 1, amount_out)
    boa.deal(borrowed_token, trader, amount_in)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange_dy(0, 1, amount_out, amount_in + 1)

    # ================= Capture initial state =================

    active_band_before = amm.active_band()
    assert active_band_before == ticks_before[0] + 2
    user_state_before = controller.user_state(borrower)
    debt = user_state_before[2]
    assert (
        0 < user_state_before[1] < debt and user_state_before[0] > 0
    )  # Position is underwater

    # ================= Verify shrink reverts =================

    with boa.reverts("Can't shrink"):
        controller.tokens_to_shrink(borrower)

    with boa.reverts("Can't shrink"):
        controller.repay_health_preview(
            0, user_state_before[1], borrower, borrower, True, False
        )

    with boa.reverts("Can't shrink"):
        controller.repay_health_preview(
            0, user_state_before[1], borrower, borrower, True, True
        )

    with boa.reverts("Can't shrink"):
        controller.approve(payer, True, sender=borrower)
        controller.repay(
            0, borrower, amm.active_band(), ZERO_ADDRESS, b"", True, sender=payer
        )
