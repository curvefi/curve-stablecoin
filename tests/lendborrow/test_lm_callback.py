import boa
import pytest


@pytest.fixture(scope="module")
def lm_callback(market_amm, market_controller, admin):
    with boa.env.prank(admin):
        cb = boa.load('contracts/testing/DummyLMCallback.vy', market_amm.address)
        market_controller.set_callback(cb.address)
        return cb


def test_lm_callback(lm_callback, market_amm, market_controller):
    pass
