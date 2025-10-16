import boa
import pytest
from textwrap import dedent

from tests.utils import filter_logs, max_approve

COLLATERAL = 10**21
DEBT = 10**18
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
            xy_borrowed: uint256,
            xy_collateral: uint256
        ):
            xy: uint256[2] = [xy_borrowed, xy_collateral]
            cb: core.IController.CallbackData = empty(core.IController.CallbackData)
            core._repay_full(_for, _d_debt, _approval, xy, cb, empty(address))
        """
        )
    )


@pytest.fixture(scope="module")
def snapshot(controller, amm, fake_leverage):
    def fn(token, borrower: str):
        return {
            "controller": token.balanceOf(controller),
            "borrower": token.balanceOf(borrower),
            "amm": token.balanceOf(amm),
            "callback": token.balanceOf(fake_leverage),
        }

    return fn


def test_default_behavior_no_callback(
    controller, borrowed_token, collateral_token, amm, snapshot
):
    borrower = boa.env.eoa

    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller)
    controller.create_loan(COLLATERAL, DEBT, N_BANDS)

    max_approve(borrowed_token, controller)
    debt = controller.debt(borrower)

    xy = amm.get_sum_xy(borrower)

    borrowed_token_before = snapshot(borrowed_token, borrower)
    collateral_token_before = snapshot(collateral_token, borrower)

    controller.inject.repay_full(borrower, debt, True, xy[0], xy[1])

    repay_logs = filter_logs(controller, "Repay")
    state_logs = filter_logs(controller, "UserState")

    borrowed_token_after = snapshot(borrowed_token, borrower)
    collateral_token_after = snapshot(collateral_token, borrower)

    borrowed_to_controller = (
        borrowed_token_after["controller"] - borrowed_token_before["controller"]
    )
    borrowed_from_borrower = (
        borrowed_token_after["borrower"] - borrowed_token_before["borrower"]
    )
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
    assert borrowed_from_borrower == -debt
    assert borrowed_token_after["amm"] == borrowed_token_before["amm"]
    assert borrowed_token_after["callback"] == borrowed_token_before["callback"]

    assert collateral_to_borrower == COLLATERAL
    assert collateral_from_amm == -COLLATERAL
    assert collateral_token_after["callback"] == collateral_token_before["callback"]
    assert collateral_token_after["controller"] == collateral_token_before["controller"]
