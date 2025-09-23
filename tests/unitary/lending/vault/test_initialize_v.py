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


def test_default_behavior(fresh_market, collateral_token, borrowed_token, proto):
    vault = fresh_market["vault"]
    controller = fresh_market["controller"]
    amm = fresh_market["amm"]

    assert vault.borrowed_token() == borrowed_token.address
    assert vault.collateral_token() == collateral_token.address
    assert vault.factory() == proto.lending_factory.address
    assert vault.amm() == amm.address
    assert vault.controller() == controller.address
    assert vault.eval("self.precision") == 10**(18 - borrowed_token.decimals())
    assert vault.name() == 'Curve Vault for ' + borrowed_token.symbol()
    assert vault.symbol() == 'cv' + borrowed_token.symbol()
    assert vault.maxSupply() == MAX_UINT256
