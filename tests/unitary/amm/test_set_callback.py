import boa
import pytest
from tests.utils import filter_logs
from tests.utils.deployers import DUMMY_LM_CALLBACK_DEPLOYER
from tests.utils.constants import ZERO_ADDRESS


@pytest.fixture(scope="module")
def market_type():
    return "lending"


@pytest.fixture(scope="module")
def collateral_decimals():
    return 18


@pytest.fixture(scope="module")
def borrowed_decimals():
    return 18


@pytest.fixture(scope="module")
def dummy_callback(amm):
    return DUMMY_LM_CALLBACK_DEPLOYER.deploy(amm)


def test_set_callback(amm, controller, dummy_callback):
    with boa.env.prank(controller.address):
        amm.set_callback(dummy_callback)
    logs = filter_logs(amm, "SetCallback")
    assert len(logs) == 1
    assert logs[0].callback == dummy_callback.address


def test_set_callback_zero_address(amm, controller):
    with boa.env.prank(controller.address):
        amm.set_callback(ZERO_ADDRESS)
    logs = filter_logs(amm, "SetCallback")
    assert len(logs) == 1
    assert logs[0].callback == ZERO_ADDRESS


def test_set_callback_non_admin_reverts(amm, dummy_callback):
    with boa.reverts():
        amm.set_callback(dummy_callback)
