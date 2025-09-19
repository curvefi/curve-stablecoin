import pytest


@pytest.fixture(scope="module")
def lending_controller(
    proto,
    collateral_token,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    price_oracle,
    min_borrow_rate,
    max_borrow_rate,
):
    market = proto.create_lending_market(
        borrowed_token=proto.crvUSD,
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
    return market["controller"]


def test_borrow_cap_default_behavior(lending_controller):
    """
    Checks that freshly deployed lending controllers have a borrow cap of zero.
    """
    assert lending_controller.borrow_cap() == 0
