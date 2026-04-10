import pytest
import boa
from tests.utils import max_approve

N_BANDS = 6


@pytest.fixture(scope="module")
def collateral_amount(collateral_token):
    return int(0.1 * 10 ** collateral_token.decimals())


@pytest.fixture(scope="module")
def debt_amount(controller, collateral_amount):
    return controller.max_borrowable(collateral_amount, N_BANDS)


@pytest.fixture(scope="function")
def borrower_with_loan(controller, collateral_token, borrowed_token, collateral_amount, debt_amount):
    """Create a standard loan for the EOA borrower."""
    borrower = boa.env.eoa
    boa.deal(collateral_token, borrower, collateral_amount)
    max_approve(collateral_token, controller)
    max_approve(borrowed_token, controller)
    controller.create_loan(collateral_amount, debt_amount, N_BANDS)
    assert controller.loan_exists(borrower)
    return borrower


def test_no_loan(controller):
    """
    user_state for an address with no loan should return all zeros.
    """
    user = boa.env.generate_address()
    state = controller.user_state(user)
    assert state[0] == 0  # collateral
    assert state[1] == 0  # borrowed in AMM
    assert state[2] == 0  # debt
    assert state[3] == 0  # N bands


def test_active_loan(controller, collateral_amount, debt_amount, borrower_with_loan):
    """
    user_state for a healthy loan with no soft-liquidation.

    Collateral is fully in AMM as collateral, no borrowed tokens in AMM.
    """
    borrower = borrower_with_loan
    state = controller.user_state(borrower)

    assert state[0] == collateral_amount  # all collateral in AMM
    assert state[1] == 0                  # no borrowed tokens in AMM
    assert state[2] == debt_amount        # full debt
    assert state[3] == N_BANDS            # N bands


def test_soft_liquidation(controller, amm, borrowed_token, collateral_amount, debt_amount, borrower_with_loan):
    """
    user_state during soft-liquidation: some collateral has been converted to
    borrowed tokens inside AMM bands (xy[0] > 0, xy[1] < original collateral).
    """
    borrower = borrower_with_loan

    # Push position into soft liquidation by having a trader swap borrowed → collateral
    trader = boa.env.generate_address()
    boa.deal(borrowed_token, trader, debt_amount // 2)
    with boa.env.prank(trader):
        max_approve(borrowed_token, amm)
        expected_collateral = amm.get_dy(0, 1, debt_amount // 2)
        amm.exchange(0, 1, debt_amount // 2, 0)

    state = controller.user_state(borrower)
    xy = amm.get_sum_xy(borrower)

    # Collateral reduced, some borrowed tokens accumulated in bands
    assert state[0] == xy[1]              # collateral remaining in AMM
    assert state[1] == xy[0]              # borrowed tokens accumulated in AMM
    assert state[2] == controller.debt(borrower)  # debt unchanged by AMM trades
    assert state[3] == N_BANDS            # N bands unchanged

    assert state[0] < collateral_amount   # less collateral than deposited: some was bought out by the trader
    assert state[1] > 0                   # borrowed tokens now in AMM: accumulated from the trader's swap
    assert state[0] == pytest.approx(collateral_amount - expected_collateral, abs=1)  # collateral reduced by approximately what the trader received
    assert state[1] == pytest.approx(debt_amount // 2, abs=1, rel=1e-10)  # borrowed in AMM approximately matches what the trader spent


def test_unrelated_user(controller, borrower_with_loan):
    """
    user_state for an address with no loan is zeros even when another user has a loan.
    """
    other_user = boa.env.generate_address()
    state = controller.user_state(other_user)

    assert state[0] == 0
    assert state[1] == 0
    assert state[2] == 0
    assert state[3] == 0


def test_after_full_repay(controller, borrowed_token, collateral_amount, debt_amount, borrower_with_loan):
    """
    user_state returns all zeros after the loan is fully repaid.
    """
    borrower = borrower_with_loan

    # Accrue a little extra debt, deal enough to cover
    boa.env.time_travel(86400)
    full_debt = controller.debt(borrower)
    boa.deal(borrowed_token, borrower, full_debt)
    controller.repay(full_debt, borrower)
    assert not controller.loan_exists(borrower)

    state = controller.user_state(borrower)
    assert state[0] == 0
    assert state[1] == 0
    assert state[2] == 0
    assert state[3] == 0


def test_debt_accrual_reflected(controller, amm, monetary_policy, admin, debt_amount, borrower_with_loan):
    """
    user_state debt field reflects accrued interest over time.
    """
    borrower = borrower_with_loan

    # Ensure a non-zero borrow rate so debt accrues
    with boa.env.prank(admin):
        monetary_policy.set_rate(10**15)
        controller.save_rate()

    boa.env.time_travel(365 * 86400)
    state = controller.user_state(borrower)
    accrued_debt = controller.debt(borrower)

    assert state[2] == accrued_debt
    assert state[2] > debt_amount  # debt grew due to interest
    assert state[0] > 0            # collateral still present
    assert state[3] == N_BANDS


def test_n_bands_matches_position(controller, collateral_token, borrowed_token):
    """
    N in user_state matches the N bands chosen at loan creation for different N values.
    """
    for n in [4, 10, 20]:
        borrower = boa.env.generate_address()
        collateral = int(0.1 * 10 ** collateral_token.decimals())
        debt = controller.max_borrowable(collateral, n, borrower)
        boa.deal(collateral_token, borrower, collateral)
        with boa.env.prank(borrower):
            max_approve(collateral_token, controller)
            max_approve(borrowed_token, controller)
            controller.create_loan(collateral, debt, n, borrower)

        state = controller.user_state(borrower)
        assert state[3] == n
