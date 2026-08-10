"""
Unit fixtures for `LMCallbackFactory`.

The factory only cares that its blueprint deploys something taking a single AMM
address, so these tests use `DummyLMCallback` rather than the real `LMCallback`
(which additionally reaches out to CRV, the GaugeController and the Minter).
That keeps the suite standalone: no protocol deployment, no market fixtures.
"""

import boa
import pytest

from tests.utils import filter_logs
from tests.utils.deployers import (
    DUMMY_LM_CALLBACK_DEPLOYER,
    LM_CALLBACK_FACTORY_DEPLOYER,
    compiler_args_default,
)

# A second callback shape, distinguishable from `DummyLMCallback` by its runtime
# code, so a deployment can be attributed to one blueprint or the other
OTHER_CALLBACK = """
# pragma version 0.4.3

AMM: public(immutable(address))
MARKER: public(constant(uint256)) = 42

@deploy
def __init__(_amm: address):
    AMM = _amm
"""


@pytest.fixture
def owner():
    return boa.env.generate_address("owner")


@pytest.fixture
def non_owner():
    return boa.env.generate_address("non_owner")


@pytest.fixture
def dummy_amm():
    """`DummyLMCallback` only stores the AMM, so it never has to be a contract."""
    return boa.env.generate_address("dummy_amm")


@pytest.fixture
def lm_callback_blueprint():
    return DUMMY_LM_CALLBACK_DEPLOYER.deploy_as_blueprint()


@pytest.fixture
def other_blueprint():
    """A valid but different blueprint, for testing blueprint rotation."""
    return boa.loads_partial(
        OTHER_CALLBACK, compiler_args=compiler_args_default
    ).deploy_as_blueprint()


@pytest.fixture
def deploy_factory():
    """Deploy a factory with explicit arguments, for tests that vary them."""

    def _deploy_factory(owner, blueprint):
        return LM_CALLBACK_FACTORY_DEPLOYER.deploy(owner, blueprint)

    return _deploy_factory


@pytest.fixture
def factory(deploy_factory, owner, lm_callback_blueprint):
    return deploy_factory(owner, lm_callback_blueprint)


@pytest.fixture
def paused_factory(factory, owner):
    factory.pause(sender=owner)
    assert factory.paused()
    return factory


@pytest.fixture
def single_factory_event():
    def _single_factory_event(factory, event_name):
        logs = filter_logs(factory, event_name)
        assert len(logs) == 1
        return logs[0]

    return _single_factory_event
