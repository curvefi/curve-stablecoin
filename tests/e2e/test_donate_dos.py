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
    controller, vault, borrowed_token, collateral_token, admin
):
    initial_balance = vault.asset_balance()

    COLLATERAL = 10**30
    N_BANDS = 5
    DONATION = 1

    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    collateral_token.approve(controller, MAX_UINT256)

    boa.deal(borrowed_token, boa.env.eoa, DONATION)
    borrowed_token.transfer(controller, DONATION)

    with boa.reverts("Borrowed balance exceeded"):
        controller.create_loan(COLLATERAL, initial_balance + DONATION, N_BANDS)

    vault.totalAssets()
