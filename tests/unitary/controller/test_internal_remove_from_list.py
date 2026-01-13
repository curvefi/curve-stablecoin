import boa
import pytest
from textwrap import dedent
from tests.utils import max_approve

N_BANDS = 6


@pytest.fixture(scope="module")
def amounts(collateral_token, borrowed_token):
    return {
        "collateral": int(1000 * 10**collateral_token.decimals()),
        "debt": int(100 * 10**borrowed_token.decimals()),
    }


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


def open_loans(controller, collateral_token, borrowers, amounts):
    assert controller.n_loans() == 0
    for index, borrower in enumerate(borrowers):
        boa.deal(collateral_token, borrower, amounts["collateral"])
        max_approve(collateral_token, controller, sender=borrower)
        controller.create_loan(amounts["collateral"], amounts["debt"], N_BANDS, sender=borrower)
        assert controller.loans(index) == borrower
        assert controller.loan_ix(borrower) == index


def test_default_behavior_single_entry(controller, collateral_token, amounts):
    borrower = boa.env.generate_address()
    open_loans(controller, collateral_token, [borrower], amounts)

    controller.inject.remove_from_list(borrower)

    assert controller.n_loans() == 0
    assert controller.loan_ix(borrower) == 0


def test_default_behavior_removing_last_entry(controller, collateral_token, amounts):
    borrowers = [boa.env.generate_address() for _ in range(3)]
    open_loans(controller, collateral_token, borrowers, amounts)

    controller.inject.remove_from_list(borrowers[-1])

    assert controller.n_loans() == 2
    assert controller.loans(0) == borrowers[0]
    assert controller.loans(1) == borrowers[1]
    assert controller.loan_ix(borrowers[0]) == 0
    assert controller.loan_ix(borrowers[1]) == 1
    assert controller.loan_ix(borrowers[2]) == 0


def test_default_behavior_swap_last_into_gap(controller, collateral_token, amounts):
    borrowers = [boa.env.generate_address() for _ in range(3)]
    open_loans(controller, collateral_token, borrowers, amounts)

    controller.inject.remove_from_list(borrowers[1])

    assert controller.n_loans() == 2
    assert controller.loans(0) == borrowers[0]
    assert controller.loans(1) == borrowers[2]
    assert controller.loan_ix(borrowers[0]) == 0
    assert controller.loan_ix(borrowers[1]) == 0
    assert controller.loan_ix(borrowers[2]) == 1
