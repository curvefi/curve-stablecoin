import boa
import pytest
from textwrap import dedent
from tests.utils import filter_logs, max_approve
from tests.utils.constants import ZERO_ADDRESS

N_BANDS = 6


@pytest.fixture(scope="module")
def collateral_amount(collateral_token):
    return int(N_BANDS * 0.05 * 10 ** collateral_token.decimals())


@pytest.fixture(scope="module", autouse=True)
def expose_internal(controller):
    controller.inject_function(
        dedent(
            """
        @external
        def repay_partial(
            _for: address,
            _debt: uint256,
            _wallet_d_debt: uint256,
            _approval: bool,
            _xy: uint256[2],
            _cb: core.IController.CallbackData,
            _callbacker: address,
            _max_active_band: int256,
            _shrink: bool
        ) -> uint256:
            return core._repay_partial(_for, _debt, _wallet_d_debt, _approval, _xy, _cb, _callbacker, _max_active_band, _shrink)
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
def test_repay_partial_from_wallet(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    admin,
    collateral_amount,
    different_payer,
):
    """
    Test partial repayment using only wallet tokens (no soft-liquidation).

    Money Flow: wallet_borrowed (wallet) → Controller
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Create loan =================

    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    controller.create_loan(collateral_amount, 10 ** borrowed_token.decimals(), N_BANDS)

    # ================= Set liquidation discount =================

    old_liquidation_discount = controller.liquidation_discount()
    new_liquidation_discount = old_liquidation_discount - 1
    controller.set_borrowing_discounts(
        controller.loan_discount(), new_liquidation_discount, sender=admin
    )

    # ================= Capture initial state =================

    debt = controller.debt(borrower)
    ticks_before = amm.read_user_tick_numbers(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert xy_before[0] == 0 and xy_before[1] > 0
    assert controller.n_loans() == 1

    # ================= Setup payer tokens =================

    wallet_borrowed = debt // 2  # Repay half the debt
    if different_payer:
        boa.deal(borrowed_token, payer, wallet_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        # _shrink == False, works both with and without approval
        with boa.env.anchor():
            controller.inject.repay_partial(
                borrower,
                debt,
                wallet_borrowed,
                False,
                xy_before,
                (0, 0, 0),
                ZERO_ADDRESS,
                2**255 - 1,
                False,
            )
            assert (
                controller.liquidation_discounts(borrower) == old_liquidation_discount
            )
        controller.inject.repay_partial(
            borrower,
            debt,
            wallet_borrowed,
            True,
            xy_before,
            (0, 0, 0),
            ZERO_ADDRESS,
            2**255 - 1,
            False,
        )

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    assert controller.liquidation_discounts(borrower) == new_liquidation_discount

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]

    # ================= Verify position state =================

    xy_after = amm.get_sum_xy(borrower)
    assert xy_after[0] == 0  # No borrowed tokens in AMM
    assert xy_after[1] == xy_before[1]  # Collateral still in AMM

    # Check that ticks moved up after partial repayment (position improved)
    ticks_after = amm.read_user_tick_numbers(borrower)
    assert ticks_after[0] > ticks_before[0]  # Lower tick moved up
    assert ticks_after[1] > ticks_before[1]  # Upper tick moved up
    assert controller.n_loans() == 1  # loan remains after partial repayment

    # ================= Verify logs =================

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert state_logs[0].collateral == xy_before[1]  # Position still has collateral
    assert state_logs[0].borrowed == 0  # No borrowed tokens in AMM (healthy position)
    assert state_logs[0].debt == debt - wallet_borrowed
    assert state_logs[0].n1 == ticks_after[0]
    assert state_logs[0].n2 == ticks_after[1]
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == wallet_borrowed
    assert (
        repay_logs[0].collateral_decrease == 0
    )  # No collateral decrease in partial repay

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
def test_repay_partial_from_callback(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    admin,
    fake_leverage,
    collateral_amount,
    different_payer,
):
    """
    Test partial repayment using wallet + callback tokens (not underwater).

    Money Flow: wallet_borrowed (wallet) + cb.borrowed (callback) → Controller
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Create loan =================

    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    controller.create_loan(collateral_amount, 10 ** borrowed_token.decimals(), N_BANDS)

    # ================= Set new liquidation discount =================

    old_liquidation_discount = controller.liquidation_discount()
    new_liquidation_discount = old_liquidation_discount - 1
    controller.set_borrowing_discounts(
        controller.loan_discount(), new_liquidation_discount, sender=admin
    )

    # ================= Capture initial state =================

    debt = controller.debt(borrower)
    ticks_before = amm.read_user_tick_numbers(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert xy_before[0] == 0 and xy_before[1] > 0  # Position is healthy
    assert controller.n_loans() == 1

    # ================= Setup callback tokens =================

    callback_borrowed = debt // 2  # Callback provides half of partial debt
    callback_collateral = collateral_amount - 2  # Some collateral from callback
    amm.withdraw(borrower, 10**18, sender=controller.address)
    collateral_token.transfer(fake_leverage, collateral_amount, sender=amm.address)
    boa.deal(borrowed_token, fake_leverage, debt - 1)
    cb = (amm.active_band(), callback_borrowed, callback_collateral)

    # ================= Capture balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        # _shrink == False, works both with and without approval
        with boa.env.anchor():
            controller.inject.repay_partial(
                borrower,
                debt,
                0,
                False,
                xy_before,
                cb,
                fake_leverage.address,
                2**255 - 1,
                False,
            )
            assert (
                controller.liquidation_discounts(borrower) == old_liquidation_discount
            )
        controller.inject.repay_partial(
            borrower,
            debt,
            0,
            True,
            xy_before,
            cb,
            fake_leverage.address,
            2**255 - 1,
            False,
        )

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    assert controller.liquidation_discounts(borrower) == new_liquidation_discount

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
    collateral_to_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_from_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    xy_after = amm.get_sum_xy(borrower)
    assert xy_after[0] == 0  # No borrowed tokens in AMM (healthy position)
    assert xy_after[1] == callback_collateral  # Collateral still in AMM

    # Check that ticks moved up after partial repayment (position improved)
    ticks_after = amm.read_user_tick_numbers(borrower)
    assert ticks_after[0] > ticks_before[0]  # Lower tick moved up
    assert ticks_after[1] > ticks_before[1]  # Upper tick moved up
    assert controller.n_loans() == 1  # loan remains after partial repayment

    # ================= Verify logs =================

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert (
        state_logs[0].collateral == callback_collateral
    )  # Position still has collateral
    assert state_logs[0].borrowed == 0  # No borrowed tokens in AMM (healthy position)
    assert state_logs[0].debt == debt - callback_borrowed
    assert state_logs[0].n1 == ticks_after[0]
    assert state_logs[0].n2 == ticks_after[1]
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == callback_borrowed
    assert repay_logs[0].collateral_decrease == xy_before[1] - callback_collateral

    # ================= Verify money flows =================

    assert borrowed_to_controller == callback_borrowed
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_token_after["payer"] == borrowed_token_before["payer"]
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_amm == callback_collateral
    assert collateral_from_callback == -callback_collateral
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_partial_from_wallet_and_callback(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    admin,
    fake_leverage,
    collateral_amount,
    different_payer,
):
    """
    Test partial repayment using wallet + callback tokens (not underwater).

    Money Flow: wallet_borrowed (wallet) + cb.borrowed (callback) → Controller
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Create loan =================

    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    controller.create_loan(collateral_amount, 10 ** borrowed_token.decimals(), N_BANDS)

    # ================= Set new liquidation discount =================

    old_liquidation_discount = controller.liquidation_discount()
    new_liquidation_discount = old_liquidation_discount - 1
    controller.set_borrowing_discounts(
        controller.loan_discount(), new_liquidation_discount, sender=admin
    )

    # ================= Capture initial state =================

    debt = controller.debt(borrower)
    ticks_before = amm.read_user_tick_numbers(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert xy_before[0] == 0 and xy_before[1] > 0  # Position is healthy
    assert controller.n_loans() == 1

    # ================= Setup payer tokens =================

    wallet_borrowed = debt // 2  # Repay half the debt
    if different_payer:
        boa.deal(borrowed_token, payer, wallet_borrowed)

    # ================= Setup callback tokens =================

    callback_borrowed = wallet_borrowed // 2  # Callback provides half of partial debt
    callback_collateral = collateral_amount - 2  # Some collateral from callback
    amm.withdraw(borrower, 10**18, sender=controller.address)
    collateral_token.transfer(fake_leverage, collateral_amount, sender=amm.address)
    boa.deal(borrowed_token, fake_leverage, debt - 1)
    cb = (amm.active_band(), callback_borrowed, callback_collateral)

    # ================= Capture balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        # _shrink == False, works both with and without approval
        with boa.env.anchor():
            controller.inject.repay_partial(
                borrower,
                debt,
                wallet_borrowed,
                False,
                xy_before,
                cb,
                fake_leverage.address,
                2**255 - 1,
                False,
            )
            assert (
                controller.liquidation_discounts(borrower) == old_liquidation_discount
            )
        controller.inject.repay_partial(
            borrower,
            debt,
            wallet_borrowed,
            True,
            xy_before,
            cb,
            fake_leverage.address,
            2**255 - 1,
            False,
        )

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    assert controller.liquidation_discounts(borrower) == new_liquidation_discount

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
    collateral_to_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_from_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    xy_after = amm.get_sum_xy(borrower)
    assert xy_after[0] == 0  # No borrowed tokens in AMM (healthy position)
    assert xy_after[1] == callback_collateral  # Collateral still in AMM

    # Check that ticks moved up after partial repayment (position improved)
    ticks_after = amm.read_user_tick_numbers(borrower)
    assert ticks_after[0] > ticks_before[0]  # Lower tick moved up
    assert ticks_after[1] > ticks_before[1]  # Upper tick moved up
    assert controller.n_loans() == 1  # loan remains after partial repayment

    # ================= Verify logs =================

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert (
        state_logs[0].collateral == callback_collateral
    )  # Position still has collateral
    assert state_logs[0].borrowed == 0  # No borrowed tokens in AMM (healthy position)
    assert state_logs[0].debt == debt - wallet_borrowed - callback_borrowed
    assert state_logs[0].n1 == ticks_after[0]
    assert state_logs[0].n2 == ticks_after[1]
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == wallet_borrowed + callback_borrowed
    assert repay_logs[0].collateral_decrease == xy_before[1] - callback_collateral

    # ================= Verify money flows =================

    assert borrowed_to_controller == wallet_borrowed + callback_borrowed
    assert borrowed_from_payer == -wallet_borrowed
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]

    assert collateral_to_amm == callback_collateral
    assert collateral_from_callback == -callback_collateral
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_partial_from_wallet_underwater(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    admin,
    fake_leverage,
    collateral_amount,
    different_payer,
):
    """
    Test partial repayment from wallet when position is underwater (soft-liquidated).

    Money Flow: wallet_borrowed (wallet) → Controller
                Position remains underwater (no collateral return)
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Create loan =================

    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    debt = controller.max_borrowable(collateral_amount, N_BANDS)
    assert debt > 0
    controller.create_loan(collateral_amount, debt, N_BANDS)

    # ================= Push position to underwater =================

    trader = boa.env.generate_address()
    boa.deal(borrowed_token, trader, debt // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange(0, 1, debt // 2, 0)

    # ================= Set new liquidation discount =================

    old_liquidation_discount = controller.liquidation_discount()
    new_liquidation_discount = old_liquidation_discount - 1
    controller.set_borrowing_discounts(
        controller.loan_discount(), new_liquidation_discount, sender=admin
    )

    # ================= Capture initial state =================

    debt = controller.debt(borrower)
    ticks_before = amm.read_user_tick_numbers(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert 0 < xy_before[0] < debt and xy_before[1] > 0  # Position is underwater
    assert controller.n_loans() == 1

    # ================= Setup payer tokens =================

    wallet_borrowed = debt // 3  # Repay 1/3 of the debt
    if different_payer:
        boa.deal(borrowed_token, payer, wallet_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        # Can't use callback underwater if _shrink == False
        with boa.reverts():
            controller.inject.repay_partial(
                borrower,
                debt,
                wallet_borrowed,
                False,
                xy_before,
                (0, 0, 0),
                fake_leverage,
                2**255 - 1,
                False,
            )
        # _shrink == False, works both with and without approval
        with boa.env.anchor():
            controller.inject.repay_partial(
                borrower,
                debt,
                wallet_borrowed,
                False,
                xy_before,
                (0, 0, 0),
                ZERO_ADDRESS,
                2**255 - 1,
                False,
            )
            assert (
                controller.liquidation_discounts(borrower) == old_liquidation_discount
            )
        controller.inject.repay_partial(
            borrower,
            debt,
            wallet_borrowed,
            True,
            xy_before,
            (0, 0, 0),
            ZERO_ADDRESS,
            2**255 - 1,
            False,
        )

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")
    assert controller.liquidation_discounts(borrower) == new_liquidation_discount

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_payer = borrowed_token_after["payer"] - borrowed_token_before["payer"]

    # ================= Verify position state =================

    xy_after = amm.get_sum_xy(borrower)
    assert xy_after[0] == xy_before[0]  # Still has borrowed tokens in AMM (underwater)
    assert xy_after[1] == xy_before[1]  # Still has collateral in AMM

    # Check that ticks stay the same after underwater partial repayment (position still underwater)
    ticks_after = amm.read_user_tick_numbers(borrower)
    assert ticks_after[0] == ticks_before[0]  # Lower tick unchanged
    assert ticks_after[1] == ticks_before[1]  # Upper tick unchanged
    assert controller.n_loans() == 1  # loan remains after partial repayment

    # ================= Verify logs =================

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert (
        state_logs[0].collateral == xy_before[1]
    )  # Collateral amount after partial repay
    assert (
        state_logs[0].borrowed == xy_before[0]
    )  # Still has borrowed tokens in AMM (underwater)
    assert state_logs[0].debt == debt - wallet_borrowed
    assert state_logs[0].n1 == ticks_after[0]
    assert state_logs[0].n2 == ticks_after[1]
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == wallet_borrowed
    assert (
        repay_logs[0].collateral_decrease == 0
    )  # No collateral decrease in underwater partial repay

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
def test_repay_partial_from_xy0_underwater_shrink(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    admin,
    fake_leverage,
    collateral_amount,
    different_payer,
):
    """
    Test partial repayment from wallet when position is underwater (soft-liquidated).

    Money Flow: xy[0] (AMM) → Controller
                Position exits from underwater (no collateral return though)
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Create loan =================

    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    debt = controller.max_borrowable(collateral_amount, N_BANDS)
    assert debt > 0
    controller.create_loan(collateral_amount, debt, N_BANDS)

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
    assert controller.tokens_to_shrink(borrower) == 0

    # ================= Set new liquidation discount =================

    old_liquidation_discount = controller.liquidation_discount()
    new_liquidation_discount = old_liquidation_discount - 1
    controller.set_borrowing_discounts(
        controller.loan_discount(), new_liquidation_discount, sender=admin
    )

    # ================= Capture initial state =================

    active_band_before = amm.active_band()
    assert active_band_before == ticks_before[0] + 1
    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert 0 < xy_before[0] < debt and xy_before[1] > 0  # Position is underwater
    assert controller.n_loans() == 1

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    with boa.env.prank(payer):
        # _shrink == True, reverts without approval
        with boa.reverts():
            controller.inject.repay_partial(
                borrower,
                debt,
                0,
                False,
                xy_before,
                (0, 0, 0),
                ZERO_ADDRESS,
                2**255 - 1,
                True,
            )
            assert (
                controller.liquidation_discounts(borrower) == old_liquidation_discount
            )
        controller.inject.repay_partial(
            borrower,
            debt,
            0,
            True,
            xy_before,
            (0, 0, 0),
            ZERO_ADDRESS,
            2**255 - 1,
            True,
        )

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")
    assert controller.liquidation_discounts(borrower) == new_liquidation_discount

    # ================= Capture final balances =================

    borrowed_token_after = snapshot(borrowed_token, borrower, payer)
    collateral_token_after = snapshot(collateral_token, borrower, payer)

    # ================= Calculate money flows =================

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_amm = borrowed_token_after["amm"] - borrowed_token_before["amm"]

    # ================= Verify position state =================

    xy_after = amm.get_sum_xy(borrower)
    assert xy_after[0] == 0  # Spent all the tokens from AMM (not underwater now)
    assert xy_after[1] == xy_before[1]  # Still has collateral in AMM

    # Check that user has exited form underwater
    ticks_after = amm.read_user_tick_numbers(borrower)
    assert (
        ticks_after[1] - ticks_after[0] + 1 == 4
    )  # Size has been shrunk from 6 bands to 4 bands
    assert (
        ticks_after[0] > active_band_before
    )  # Lower tick is higher than active_band before
    assert (
        ticks_after[1] >= ticks_before[1]
    )  # Upper tick is higher or the same as before
    assert amm.active_band() == active_band_before  # Active band unchanged
    assert controller.n_loans() == 1  # loan remains after partial repayment

    # ================= Verify logs =================

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert (
        state_logs[0].collateral == xy_before[1]
    )  # Collateral amount after partial repay
    assert state_logs[0].borrowed == 0  # No borrowed tokens in AMM (exited underwater)
    assert state_logs[0].debt == debt - xy_before[0]
    assert state_logs[0].n1 == ticks_after[0]
    assert state_logs[0].n2 == ticks_after[1]
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == xy_before[0]
    assert (
        repay_logs[0].collateral_decrease == 0
    )  # No collateral decrease in underwater partial repay

    # ================= Verify money flows =================

    assert borrowed_to_controller == xy_before[0]
    assert borrowed_from_amm == -xy_before[0]
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
def test_repay_partial_from_xy0_and_wallet_underwater_shrink(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    admin,
    fake_leverage,
    collateral_amount,
    different_payer,
):
    """
    Test partial repayment from wallet when position is underwater (soft-liquidated).

    Money Flow: wallet_borrowed (wallet) + xy[0] (AMM) → Controller
                Position exits from underwater (no collateral return though)
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Create loan =================

    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    debt = controller.max_borrowable(collateral_amount, N_BANDS)
    assert debt > 0
    controller.create_loan(collateral_amount, debt, N_BANDS)

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
    amount_in = amm.get_dx(0, 1, amount_out)
    boa.deal(borrowed_token, trader, amount_in)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange_dy(0, 1, amount_out, amount_in + 1)
    assert controller.user_state(borrower)[1] > 0
    tokens_to_shrink = controller.tokens_to_shrink(borrower)
    assert tokens_to_shrink > 0

    # ================= Set new liquidation discount =================

    old_liquidation_discount = controller.liquidation_discount()
    new_liquidation_discount = old_liquidation_discount - 1
    controller.set_borrowing_discounts(
        controller.loan_discount(), new_liquidation_discount, sender=admin
    )

    # ================= Capture initial state =================

    active_band_before = amm.active_band()
    assert active_band_before == ticks_before[0]
    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert 0 < xy_before[0] < debt and xy_before[1] > 0  # Position is underwater
    assert controller.n_loans() == 1

    # ================= Setup payer tokens =================

    if different_payer:
        boa.deal(borrowed_token, payer, tokens_to_shrink)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        # _shrink == True, reverts without approval
        with boa.reverts():
            controller.inject.repay_partial(
                borrower,
                debt,
                tokens_to_shrink,
                False,
                xy_before,
                (0, 0, 0),
                ZERO_ADDRESS,
                2**255 - 1,
                True,
            )
            assert (
                controller.liquidation_discounts(borrower) == old_liquidation_discount
            )
        controller.inject.repay_partial(
            borrower,
            debt,
            tokens_to_shrink,
            True,
            xy_before,
            (0, 0, 0),
            ZERO_ADDRESS,
            2**255 - 1,
            True,
        )

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")
    assert controller.liquidation_discounts(borrower) == new_liquidation_discount

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

    xy_after = amm.get_sum_xy(borrower)
    assert xy_after[0] == 0  # Spent all the tokens from AMM (not underwater now)
    assert xy_after[1] == xy_before[1]  # Still has collateral in AMM

    # Check that user has exited form underwater
    ticks_after = amm.read_user_tick_numbers(borrower)
    assert (
        ticks_after[1] - ticks_after[0] + 1 == 5
    )  # Size has been shrunk from 6 bands to 5 bands
    assert (
        ticks_after[0] > active_band_before
    )  # Lower tick is higher than active_band before
    assert (
        ticks_after[1] >= ticks_before[1]
    )  # Upper tick is higher or the same as before
    assert amm.active_band() == active_band_before  # Active band unchanged
    assert controller.n_loans() == 1  # loan remains after partial repayment

    # ================= Verify logs =================

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert (
        state_logs[0].collateral == xy_before[1]
    )  # Collateral amount after partial repay
    assert state_logs[0].borrowed == 0  # No borrowed tokens in AMM (exited underwater)
    assert state_logs[0].debt == debt - xy_before[0] - tokens_to_shrink
    assert state_logs[0].n1 == ticks_after[0]
    assert state_logs[0].n2 == ticks_after[1]
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == xy_before[0] + tokens_to_shrink
    assert (
        repay_logs[0].collateral_decrease == 0
    )  # No collateral decrease in underwater partial repay

    # ================= Verify money flows =================

    assert borrowed_to_controller == xy_before[0] + tokens_to_shrink
    assert borrowed_from_amm == -xy_before[0]
    assert borrowed_from_payer == -tokens_to_shrink
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]
    assert collateral_token_after["amm"] == collateral_token_before["amm"]
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_partial_from_xy0_and_callback_underwater_shrink(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    admin,
    fake_leverage,
    collateral_amount,
    different_payer,
):
    """
    Test partial repayment from callback when position is underwater (soft-liquidated).

    Money Flow: xy[0] (AMM) + cb.borrowed (callback) → Controller
                Position exits from underwater (no collateral return though)
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Create loan =================

    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    debt = controller.max_borrowable(collateral_amount, N_BANDS)
    assert debt > 0
    controller.create_loan(collateral_amount, debt, N_BANDS)

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
    amount_in = amm.get_dx(0, 1, amount_out)
    boa.deal(borrowed_token, trader, amount_in)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange_dy(0, 1, amount_out, amount_in + 1)
    assert controller.user_state(borrower)[1] > 0

    # ================= Get tokens_to_shrink =================

    d_collateral = 2  # The amount of user's position collateral to be used by callback
    tokens_to_shrink = controller.tokens_to_shrink(borrower, d_collateral)
    assert tokens_to_shrink > 0

    # ================= Set new liquidation discount =================

    old_liquidation_discount = controller.liquidation_discount()
    new_liquidation_discount = old_liquidation_discount - 1
    controller.set_borrowing_discounts(
        controller.loan_discount(), new_liquidation_discount, sender=admin
    )

    # ================= Capture initial state =================

    active_band_before = amm.active_band()
    assert active_band_before == ticks_before[0]
    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert 0 < xy_before[0] < debt and xy_before[1] > 0  # Position is underwater
    assert controller.n_loans() == 1

    # ================= Setup callback tokens =================

    callback_borrowed = tokens_to_shrink  # Callback provides tokens_to_shrink
    callback_collateral = xy_before[1] - d_collateral  # Some collateral from callback
    amm.withdraw(borrower, 10**18, sender=controller.address)
    collateral_token.transfer(fake_leverage, xy_before[1], sender=amm.address)
    boa.deal(borrowed_token, fake_leverage, callback_borrowed)
    cb = (amm.active_band(), callback_borrowed, callback_collateral)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    with boa.env.prank(payer):
        # _shrink == True, reverts without approval
        with boa.reverts():
            controller.inject.repay_partial(
                borrower,
                debt,
                0,
                False,
                xy_before,
                cb,
                fake_leverage.address,
                2**255 - 1,
                True,
            )
            assert (
                controller.liquidation_discounts(borrower) == old_liquidation_discount
            )
        controller.inject.repay_partial(
            borrower,
            debt,
            0,
            True,
            xy_before,
            cb,
            fake_leverage.address,
            2**255 - 1,
            True,
        )

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")
    assert controller.liquidation_discounts(borrower) == new_liquidation_discount

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
    collateral_to_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_from_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    xy_after = amm.get_sum_xy(borrower)
    assert xy_after[0] == 0  # Spent all the tokens from AMM (not underwater now)
    assert xy_after[1] == callback_collateral  # Still has collateral in AMM

    # Check that user has exited form underwater
    ticks_after = amm.read_user_tick_numbers(borrower)
    assert (
        ticks_after[1] - ticks_after[0] + 1 == 5
    )  # Size has been shrunk from 6 bands to 5 bands
    assert (
        ticks_after[0] > active_band_before
    )  # Lower tick is higher than active_band before
    assert (
        ticks_after[1] >= ticks_before[1]
    )  # Upper tick is higher or the same as before
    assert amm.active_band() == active_band_before  # Active band unchanged
    assert controller.n_loans() == 1  # loan remains after partial repayment

    # ================= Verify logs =================

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert (
        state_logs[0].collateral == callback_collateral
    )  # Collateral amount after partial repay
    assert state_logs[0].borrowed == 0  # No borrowed tokens in AMM (exited underwater)
    assert state_logs[0].debt == debt - xy_before[0] - callback_borrowed
    assert state_logs[0].n1 == ticks_after[0]
    assert state_logs[0].n2 == ticks_after[1]
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert repay_logs[0].loan_decrease == xy_before[0] + callback_borrowed
    assert repay_logs[0].collateral_decrease == xy_before[1] - callback_collateral

    # ================= Verify money flows =================

    assert borrowed_to_controller == xy_before[0] + callback_borrowed
    assert borrowed_from_amm == -xy_before[0]
    assert borrowed_from_callback == -callback_borrowed
    assert borrowed_token_after["payer"] == borrowed_token_before["payer"]

    assert collateral_to_amm == callback_collateral
    assert collateral_from_callback == -callback_collateral
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_partial_from_xy0_and_wallet_and_callback_underwater_shrink(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    admin,
    fake_leverage,
    collateral_amount,
    different_payer,
):
    """
    Test partial repayment from callback when position is underwater (soft-liquidated).

    Money Flow: xy[0] (AMM) + cb.borrowed (callback) → Controller
                Position exits from underwater (no collateral return though)
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Create loan =================

    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    debt = controller.max_borrowable(collateral_amount, N_BANDS)
    assert debt > 0
    controller.create_loan(collateral_amount, debt, N_BANDS)

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
    amount_in = amm.get_dx(0, 1, amount_out)
    boa.deal(borrowed_token, trader, amount_in)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        amm.exchange_dy(0, 1, amount_out, amount_in + 1)
    assert controller.user_state(borrower)[1] > 0

    # ================= Get tokens_to_shrink =================

    d_collateral = 2  # The amount of user's position collateral to be used by callback
    tokens_to_shrink = controller.tokens_to_shrink(borrower, d_collateral)
    assert tokens_to_shrink > 0

    # ================= Set new liquidation discount =================

    old_liquidation_discount = controller.liquidation_discount()
    new_liquidation_discount = old_liquidation_discount - 1
    controller.set_borrowing_discounts(
        controller.loan_discount(), new_liquidation_discount, sender=admin
    )

    # ================= Capture initial state =================

    active_band_before = amm.active_band()
    assert active_band_before == ticks_before[0]
    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert 0 < xy_before[0] < debt and xy_before[1] > 0  # Position is underwater
    assert controller.n_loans() == 1

    # ================= Setup callback tokens =================

    callback_borrowed = tokens_to_shrink // 2  # Callback provides tokens_to_shrink
    callback_collateral = xy_before[1] - d_collateral  # Some collateral from callback
    amm.withdraw(borrower, 10**18, sender=controller.address)
    collateral_token.transfer(fake_leverage, xy_before[1], sender=amm.address)
    boa.deal(borrowed_token, fake_leverage, callback_borrowed)
    cb = (amm.active_band(), callback_borrowed, callback_collateral)

    # ================= Setup payer tokens =================

    wallet_borrowed = tokens_to_shrink - callback_borrowed
    if different_payer:
        boa.deal(borrowed_token, payer, wallet_borrowed)

    # ================= Capture initial balances =================

    borrowed_token_before = snapshot(borrowed_token, borrower, payer)
    collateral_token_before = snapshot(collateral_token, borrower, payer)

    # ================= Execute partial repayment =================

    with boa.env.prank(payer):
        max_approve(borrowed_token, controller)
        # _shrink == True, reverts without approval
        with boa.reverts():
            controller.inject.repay_partial(
                borrower,
                debt,
                wallet_borrowed,
                False,
                xy_before,
                cb,
                fake_leverage.address,
                2**255 - 1,
                True,
            )
            assert (
                controller.liquidation_discounts(borrower) == old_liquidation_discount
            )
        controller.inject.repay_partial(
            borrower,
            debt,
            wallet_borrowed,
            True,
            xy_before,
            cb,
            fake_leverage.address,
            2**255 - 1,
            True,
        )

    # ================= Capture logs =================

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")
    assert controller.liquidation_discounts(borrower) == new_liquidation_discount

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
    collateral_to_amm = collateral_token_after["amm"] - collateral_token_before["amm"]
    collateral_from_callback = (
        collateral_token_after["callback"] - collateral_token_before["callback"]
    )

    # ================= Verify position state =================

    xy_after = amm.get_sum_xy(borrower)
    assert xy_after[0] == 0  # Spent all the tokens from AMM (not underwater now)
    assert xy_after[1] == callback_collateral  # Still has collateral in AMM

    # Check that user has exited form underwater
    ticks_after = amm.read_user_tick_numbers(borrower)
    assert (
        ticks_after[1] - ticks_after[0] + 1 == 5
    )  # Size has been shrunk from 6 bands to 5 bands
    assert (
        ticks_after[0] > active_band_before
    )  # Lower tick is higher than active_band before
    assert (
        ticks_after[1] >= ticks_before[1]
    )  # Upper tick is higher or the same as before
    assert amm.active_band() == active_band_before  # Active band unchanged
    assert controller.n_loans() == 1  # loan remains after partial repayment

    # ================= Verify logs =================

    assert len(state_logs) == 1
    assert state_logs[0].user == borrower
    assert (
        state_logs[0].collateral == callback_collateral
    )  # Collateral amount after partial repay
    assert state_logs[0].borrowed == 0  # No borrowed tokens in AMM (exited underwater)
    assert (
        state_logs[0].debt == debt - xy_before[0] - callback_borrowed - wallet_borrowed
    )
    assert state_logs[0].n1 == ticks_after[0]
    assert state_logs[0].n2 == ticks_after[1]
    assert state_logs[0].liquidation_discount == controller.liquidation_discounts(
        borrower
    )

    assert len(repay_logs) == 1
    assert repay_logs[0].user == borrower
    assert (
        repay_logs[0].loan_decrease
        == xy_before[0] + callback_borrowed + wallet_borrowed
    )
    assert repay_logs[0].collateral_decrease == xy_before[1] - callback_collateral

    # ================= Verify money flows =================

    assert borrowed_to_controller == xy_before[0] + callback_borrowed + wallet_borrowed
    assert borrowed_from_payer == -wallet_borrowed
    assert borrowed_from_amm == -xy_before[0]
    assert borrowed_from_callback == -callback_borrowed

    assert collateral_to_amm == callback_collateral
    assert collateral_from_callback == -callback_collateral
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
    assert collateral_token_after["borrower"] == collateral_token_before["borrower"]

    if different_payer:
        assert borrowed_token_after["borrower"] == borrowed_token_before["borrower"]
        assert collateral_token_after["payer"] == collateral_token_before["payer"]


@pytest.mark.parametrize("different_payer", [True, False])
def test_repay_partial_cannot_shrink(
    controller,
    borrowed_token,
    collateral_token,
    amm,
    snapshot,
    admin,
    fake_leverage,
    collateral_amount,
    different_payer,
):
    """
    Test that attempt to shrink the position to less than 4 bands reverts
    """
    borrower = payer = boa.env.eoa
    if different_payer:
        payer = boa.env.generate_address()

    # ================= Create loan =================

    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    debt = controller.max_borrowable(collateral_amount, N_BANDS)
    assert debt > 0
    controller.create_loan(collateral_amount, debt, N_BANDS)

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
    debt = controller.debt(borrower)
    xy_before = amm.get_sum_xy(borrower)
    assert 0 < xy_before[0] < debt and xy_before[1] > 0  # Position is underwater
    assert controller.n_loans() == 1

    # ================= Execute partial repayment =================

    with boa.reverts("Can't shrink"):
        controller.tokens_to_shrink(borrower)

    with boa.env.prank(payer):
        with boa.reverts("Can't shrink"):
            controller.inject.repay_partial(
                borrower,
                debt,
                0,
                True,
                xy_before,
                (0, 0, 0),
                ZERO_ADDRESS,
                2**255 - 1,
                True,
            )
