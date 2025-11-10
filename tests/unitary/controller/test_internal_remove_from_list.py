import boa
import pytest
from textwrap import dedent

from tests.utils import max_approve

COLLATERAL = 10**21
DEBT = 10**18
N_BANDS = 6


@pytest.fixture(scope="module", autouse=True)
def expose_internal(controller):
    controller.inject_function(
        dedent(
            """
        @external
        def remove_from_list(_for: address):
            core._remove_from_list(_for)
        """
        )
    )


def open_loans(controller, collateral_token, borrowers):
    assert controller.n_loans() == 0
    for index, borrower in enumerate(borrowers):
        boa.deal(collateral_token, borrower, COLLATERAL)
        max_approve(collateral_token, controller, sender=borrower)
        controller.create_loan(COLLATERAL, DEBT, N_BANDS, sender=borrower)
        assert controller.loans(index) == borrower
        assert controller.loan_ix(borrower) == index


def test_default_behavior_single_entry(controller, collateral_token):
    borrower = boa.env.generate_address()
    open_loans(controller, collateral_token, [borrower])

    controller.inject.remove_from_list(borrower)

    assert controller.n_loans() == 0
    assert controller.loan_ix(borrower) == 0


def test_default_behavior_removing_last_entry(controller, collateral_token):
    borrowers = [boa.env.generate_address() for _ in range(3)]
    open_loans(controller, collateral_token, borrowers)

    controller.inject.remove_from_list(borrowers[-1])

    assert controller.n_loans() == 2
    assert controller.loans(0) == borrowers[0]
    assert controller.loans(1) == borrowers[1]
    assert controller.loan_ix(borrowers[0]) == 0
    assert controller.loan_ix(borrowers[1]) == 1
    assert controller.loan_ix(borrowers[2]) == 0


def test_default_behavior_swap_last_into_gap(controller, collateral_token):
    borrowers = [boa.env.generate_address() for _ in range(3)]
    open_loans(controller, collateral_token, borrowers)

    controller.inject.remove_from_list(borrowers[1])

    assert controller.n_loans() == 2
    assert controller.loans(0) == borrowers[0]
    assert controller.loans(1) == borrowers[2]
    assert controller.loan_ix(borrowers[0]) == 0
    assert controller.loan_ix(borrowers[1]) == 0
    assert controller.loan_ix(borrowers[2]) == 1
