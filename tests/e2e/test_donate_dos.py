import boa
import pytest

from tests.utils.constants import MAX_UINT256


@pytest.fixture(scope="module")
def market_type():
    return "lending"


@pytest.fixture(scope="module")
def borrow_cap():
    return MAX_UINT256


def test_reverts_when_lent_exceeds_deposited_under_donation(
    controller, vault, borrowed_token, collateral_token
):
    """
    Test that verifies that issue: CS-CRVUSD-094 is fixed
    as the pool doesn't allow donated tokens to be lent out.
    """
    initial_balance = vault.net_deposits()

    COLLATERAL = 10**12 * 10 ** collateral_token.decimals()
    N_BANDS = 5
    DONATION = 1

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    collateral_token.approve(controller, MAX_UINT256)

    boa.deal(borrowed_token, boa.env.eoa, DONATION)
    borrowed_token.transfer(controller, DONATION)

    with boa.reverts("Available balance exceeded"):
        controller.create_loan(COLLATERAL, initial_balance + DONATION, N_BANDS)

    vault.totalAssets()
