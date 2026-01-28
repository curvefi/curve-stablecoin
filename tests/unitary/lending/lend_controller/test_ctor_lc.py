import pytest
from tests.utils.constants import MAX_UINT256


@pytest.fixture(scope="module")
def fresh_market(
    proto,
    borrowed_token,
    collateral_token,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    price_oracle,
    min_borrow_rate,
    max_borrow_rate,
):
    return proto.create_lending_market(
        borrowed_token=borrowed_token,
        collateral_token=collateral_token,
        A=amm_A,
        fee=amm_fee,
        loan_discount=loan_discount,
        liquidation_discount=liquidation_discount,
        price_oracle=price_oracle,
        name="Borrow Cap",
        min_borrow_rate=min_borrow_rate,
        max_borrow_rate=max_borrow_rate,
        seed_amount=0,
    )


def test_default_behavior(fresh_market, borrowed_token, proto):
    """
    Checks that freshly deployed lending controllers have a borrow cap of zero,
    right vault address and infinite allowance to the vault.
    """
    controller = fresh_market["controller"]
    vault = fresh_market["vault"]

    assert controller.vault() == vault.address
    assert controller.borrow_cap() == 0
    approved = borrowed_token.allowance(controller, vault)
    assert approved == MAX_UINT256
