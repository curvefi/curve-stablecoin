import boa
import pytest
from tests.utils.deployers import FAKE_LEVERAGE_DEPLOYER
from tests.utils.deployers import SEMILOG_MONETARY_POLICY_DEPLOYER


@pytest.fixture(scope="module")
def market_type():
    """Force lending-only markets for tests in this folder."""
    return "lending"


@pytest.fixture(scope="module")
def lending_monetary_policy():
    """Override lending policy to Semilog for all tests in this folder."""
    return SEMILOG_MONETARY_POLICY_DEPLOYER


@pytest.fixture(scope="module")
def fake_leverage(collateral_token, borrowed_token, controller, admin):
    with boa.env.prank(admin):
        leverage = FAKE_LEVERAGE_DEPLOYER.deploy(
            borrowed_token.address,
            collateral_token.address,
            controller.address,
            3000 * 10**18,
        )
        boa.deal(collateral_token, leverage.address, 1000 * 10**collateral_token.decimals())
        return leverage
