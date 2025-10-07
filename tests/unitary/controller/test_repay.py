import boa

from tests.utils import max_approve
from tests.utils.constants import MAX_INT256, MAX_UINT256

COLLATERAL = 10**21
DEBT = 10**18
N_BANDS = 6


def loan_state(controller, user):
    return controller.eval(
        f"(core.loan[{user}].initial_debt, core.loan[{user}].rate_mul)"
    )


def open_loan(controller, collateral_token, borrowed_token):
    borrower = boa.env.eoa
    boa.deal(collateral_token, borrower, COLLATERAL)
    max_approve(collateral_token, controller)
    controller.create_loan(COLLATERAL, DEBT, N_BANDS)
    debt, _ = loan_state(controller, borrower)
    assert debt == DEBT
    max_approve(borrowed_token, controller)
    return borrower


def test_default_behavior_full_repay(controller, borrowed_token, collateral_token):
    borrower = open_loan(controller, collateral_token, borrowed_token)
    repaid_before = controller.repaid()

    controller.repay(MAX_UINT256, borrower)

    debt, _ = loan_state(controller, borrower)
    assert debt == 0
    assert controller.repaid() == repaid_before + DEBT


def test_default_behavior_partial_repay(controller, borrowed_token, collateral_token):
    borrower = open_loan(controller, collateral_token, borrowed_token)
    partial = DEBT // 2
    repaid_before = controller.repaid()

    controller.repay(partial, borrower)

    debt, _ = loan_state(controller, borrower)
    assert debt == DEBT - partial
    assert controller.repaid() == repaid_before + partial


def test_default_behavior_with_callback(
    controller, borrowed_token, collateral_token, fake_leverage, amm
):
    borrower = open_loan(controller, collateral_token, borrowed_token)
    xy = amm.get_sum_xy(borrower)

    boa.deal(collateral_token, fake_leverage.address, xy[1])
    boa.deal(borrowed_token, fake_leverage.address, DEBT)
    hits_before = fake_leverage.callback_repay_hits()

    controller.approve(fake_leverage.address, True)
    controller.repay(
        MAX_UINT256,
        borrower,
        MAX_INT256,
        fake_leverage.address,
        (0).to_bytes(32, "big"),
    )

    debt, _ = loan_state(controller, borrower)
    assert debt == 0
    assert fake_leverage.callback_repay_hits() == hits_before + 1


def test_callback_needs_approval(
    controller, borrowed_token, collateral_token, fake_leverage, amm
):
    borrower = open_loan(controller, collateral_token, borrowed_token)
    xy = amm.get_sum_xy(borrower)

    boa.deal(collateral_token, fake_leverage.address, xy[1])
    boa.deal(borrowed_token, fake_leverage.address, DEBT)

    repayer = boa.env.generate_address("repayer")
    boa.deal(borrowed_token, repayer, DEBT)

    with boa.reverts(dev="need approval for callback"):
        controller.repay(
            DEBT,
            borrower,
            MAX_INT256,
            fake_leverage.address,
            (0).to_bytes(32, "big"),
            sender=repayer,
        )
