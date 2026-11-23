"""Fixtures for HyperbolicMP unit tests.

Unlike HyperbolicDynamicMP, this policy has no external rate calculator and no
EMA: the base rate is a fixed `target_rate` set at construction and adjustable
by the factory admin. Only the controller is mocked here:
  * CONTROLLER -> MockControllerMP (settable accounting; returns a configurable
                  factory address)

The controller's factory is a tiny inline mock exposing a settable `admin`,
which the policy resolves via `CONTROLLER.factory().admin()` for access control
on `set_parameters`.

The curve math is identical to the dynamic policy, so the shared Python
reference model (tests.utils.hyperbolic_mp_reference) and its constants are
reused directly.
"""

import pytest
import boa

from tests.utils import hyperbolic_mp_reference as ref

from tests.utils.deployers import (
    HYPERBOLIC_MP_DEPLOYER,
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
    return HYPERBOLIC_MP_DEPLOYER


@pytest.fixture(scope="module")
def admin():
    return boa.env.generate_address("admin")


@pytest.fixture
def factory(admin):
    """Fresh tiny factory mock with `admin` as its admin."""
    return boa.loads(_FACTORY_MOCK, admin)


@pytest.fixture
def controller(factory):
    """Fresh mock controller returning `factory` as its factory."""
    return MOCK_CONTROLLER_MP_DEPLOYER.deploy(factory.address)


@pytest.fixture
def default_curve():
    """Default curve shape (target_utilization, low_ratio, high_ratio).

    Kept separate from `target_rate` and `rate_shift` so tests can feed the
    triple straight into `ref.get_params(*default_curve)`.
    """
    return (
        ref.DEFAULT_TARGET_UTILIZATION,
        ref.DEFAULT_LOW_RATIO,
        ref.DEFAULT_HIGH_RATIO,
    )


@pytest.fixture
def target_rate():
    """Default fixed base rate (within [MIN_TARGET_RATE, MAX_TARGET_RATE])."""
    return ref.DEFAULT_RATE


@pytest.fixture
def default_params(default_curve, target_rate):
    """Constructor args (sans controller/shift) in on-chain order.

    Ordered as (target_utilization, target_rate, low_ratio, high_ratio) so tests
    can deploy with `deployer.deploy(controller.address, *default_params, 0)`.
    """
    u0, alpha, beta = default_curve
    return (u0, target_rate, alpha, beta)


@pytest.fixture
def mp(deployer, controller, default_params):
    """HyperbolicMP wired to the mock controller with default parameters (shift 0)."""
    return deployer.deploy(
        controller.address,
        *default_params,
        0,
    )
