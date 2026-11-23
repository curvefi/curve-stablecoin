"""Fixtures for HyperbolicDynamicMP unit tests.

The policy has two external collaborators, both mocked here so the tests stay
unit-scoped:
  * RATE_CALCULATOR -> MockRateCalculator (settable rate, toggleable revert)
  * CONTROLLER      -> MockControllerMP (settable accounting; returns a
                       configurable factory address)

The controller's factory is a tiny inline mock exposing a settable `admin`,
which the policy resolves via `CONTROLLER.factory().admin()` for access
control on `set_parameters`.
"""

import pytest
import boa

from tests.utils import hyperbolic_mp_reference as ref

from tests.utils.deployers import (
    HYPERBOLIC_DYNAMIC_MP_DEPLOYER,
    MOCK_RATE_CALCULATOR_DEPLOYER,
    MOCK_CONTROLLER_MP_DEPLOYER,
)

# Tiny factory stand-in: just a settable `admin()` getter.
_FACTORY_MOCK = """
admin: public(address)

@deploy
def __init__(_admin: address):
    self.admin = _admin

@external
def set_admin(_admin: address):
    self.admin = _admin
"""


@pytest.fixture(scope="module")
def deployer():
    return HYPERBOLIC_DYNAMIC_MP_DEPLOYER


@pytest.fixture(scope="module")
def admin():
    return boa.env.generate_address("admin")


@pytest.fixture
def rate_calculator():
    """Fresh mock rate calculator seeded with the default per-second rate."""
    return MOCK_RATE_CALCULATOR_DEPLOYER.deploy(ref.DEFAULT_RATE)


@pytest.fixture
def factory(admin):
    """Fresh tiny factory mock with `admin` as its admin."""
    return boa.loads(_FACTORY_MOCK, admin)


@pytest.fixture
def controller(factory):
    """Fresh mock controller returning `factory` as its factory."""
    return MOCK_CONTROLLER_MP_DEPLOYER.deploy(factory.address)


@pytest.fixture
def default_params():
    """Default curve shape (target_utilization, low_ratio, high_ratio).

    The rate_shift is kept out of here (it's 0 for the default curve) and passed
    explicitly at deploy time, so tests can slot in `*default_params` directly.
    """
    return (
        ref.DEFAULT_TARGET_UTILIZATION,
        ref.DEFAULT_LOW_RATIO,
        ref.DEFAULT_HIGH_RATIO,
    )


@pytest.fixture
def mp(deployer, controller, rate_calculator, default_params):
    """HyperbolicDynamicMP wired to the mocks with default parameters (shift 0)."""
    return deployer.deploy(
        controller.address,
        rate_calculator.address,
        *default_params,
        0,
    )
