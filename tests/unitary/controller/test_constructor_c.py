import boa
import pytest

from tests.utils.constants import WAD
from tests.utils.deployers import ERC20_MOCK_DEPLOYER

VALID_LOAN_DISCOUNT = int(0.09 * 10**18)
VALID_LIQUIDATION_DISCOUNT = int(0.06 * 10**18)


@pytest.fixture
def create_market(proto, price_oracle):
    def _create_market(loan_discount, liquidation_discount):
        borrowed = ERC20_MOCK_DEPLOYER.deploy(18)
        collateral = ERC20_MOCK_DEPLOYER.deploy(18)
        return proto.create_lending_market(
            borrowed_token=borrowed,
            collateral_token=collateral,
            A=100,
            fee=10**16,
            loan_discount=loan_discount,
            liquidation_discount=liquidation_discount,
            price_oracle=price_oracle,
            min_borrow_rate=10**15 // (365 * 86400),
            max_borrow_rate=10**18 // (365 * 86400),
        )

    return _create_market


def test_revert_liquidation_discount_zero(create_market):
    with boa.reverts("liquidation discount == 0"):
        create_market(VALID_LOAN_DISCOUNT, 0)


def test_revert_loan_discount_gte_wad(create_market):
    with boa.reverts("loan discount == 100%"):
        create_market(WAD, VALID_LIQUIDATION_DISCOUNT)

    with boa.reverts("loan discount > 100%"):
        create_market(WAD + 1, VALID_LIQUIDATION_DISCOUNT)


def test_revert_loan_discount_lte_liquidation_discount(create_market):
    with boa.reverts("loan discount < liquidation discount"):
        create_market(VALID_LIQUIDATION_DISCOUNT, VALID_LOAN_DISCOUNT)

    with boa.reverts("loan discount == liquidation discount"):
        create_market(VALID_LIQUIDATION_DISCOUNT, VALID_LIQUIDATION_DISCOUNT)
