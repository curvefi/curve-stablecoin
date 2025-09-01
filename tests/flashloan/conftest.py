import boa
import pytest
from tests.utils.deployers import (
    FLASH_LENDER_DEPLOYER,
    DUMMY_FLASH_BORROWER_DEPLOYER
)


@pytest.fixture(scope="module")
def controller_factory(proto):
    """Return the preconfigured mint factory from Protocol."""
    return proto.mint_factory


@pytest.fixture(scope="module")
def max_flash_loan():
    return 3 * 10**6 * 10 ** 18


@pytest.fixture(scope="module")
def flash_lender(controller_factory, admin, max_flash_loan):
    with boa.env.prank(admin):
        fl = FLASH_LENDER_DEPLOYER.deploy(controller_factory.address)
        controller_factory.set_debt_ceiling(fl.address, max_flash_loan)
        return fl


@pytest.fixture(scope="module")
def flash_borrower(flash_lender, admin):
    with boa.env.prank(admin):
        return DUMMY_FLASH_BORROWER_DEPLOYER.deploy(flash_lender.address)
