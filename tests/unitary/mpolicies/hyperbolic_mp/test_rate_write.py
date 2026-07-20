"""Tests for rate_write(): access control and equality with rate().

Unlike the dynamic policy, this is a static-rate MP: rate_write() updates no
state and always returns the same value as rate().
"""

import pytest
import boa

from tests.utils import hyperbolic_mp_reference as ref
from tests.utils.deployers import MOCK_CONTROLLER_MP_DEPLOYER


@pytest.fixture
def controller(factory):
    """Fresh mock controller (u = 0.5) returning `factory` as its factory."""
    _controller = MOCK_CONTROLLER_MP_DEPLOYER.deploy(factory.address)
    _controller.set_state(50 * 10**18, 50 * 10**18, 0)
    return _controller


def test_rate_write_only_controller(mp):
    stranger = boa.env.generate_address("stranger")
    with boa.env.prank(stranger):
        with boa.reverts("Controller only"):
            mp.rate_write()


def test_rate_write_matches_rate(mp, controller, default_curve, target_rate):
    params = ref.get_params(*default_curve)
    u = ref.utilization(
        controller.available_balance(), controller.total_debt(), 0
    )  # controller state -> u = 0.5
    with boa.env.prank(controller.address):
        assert (
            mp.rate_write() == mp.rate() == ref.calculate_rate(params, u, target_rate)
        )


def test_rate_write_is_stateless(mp, controller):
    # Repeated calls return the same value; nothing accrues or drifts.
    with boa.env.prank(controller.address):
        first = mp.rate_write()
        boa.env.time_travel(seconds=10 * 24 * 3600)
        second = mp.rate_write()
    assert first == second == mp.rate()
