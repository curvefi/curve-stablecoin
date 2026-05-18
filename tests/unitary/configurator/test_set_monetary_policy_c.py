import boa
import pytest

from tests.utils.deployers import CONSTANT_MONETARY_POLICY_DEPLOYER


RATE_WRITE_TRACKING_MONETARY_POLICY = """
# pragma version 0.4.3

interface IController:
    def monetary_policy() -> address: view

controller: immutable(address)
rate: public(uint256)
rate_write_calls: public(uint256)

@deploy
def __init__(_controller: address, _rate: uint256):
    controller = _controller
    self.rate = _rate

@external
def rate_write() -> uint256:
    assert staticcall IController(controller).monetary_policy() == self
    self.rate_write_calls += 1
    return self.rate
"""


@pytest.fixture
def replacement_monetary_policy(admin):
    return CONSTANT_MONETARY_POLICY_DEPLOYER.deploy(admin)


def test_set_monetary_policy_updates_controller_monetary_policy(
    configurator, controller, admin, replacement_monetary_policy
):
    assert controller.monetary_policy() != replacement_monetary_policy.address

    configurator.set_monetary_policy(
        controller, replacement_monetary_policy, sender=admin
    )

    assert controller.monetary_policy() == replacement_monetary_policy.address


def test_set_monetary_policy_emits_set_monetary_policy(
    configurator,
    controller,
    admin,
    replacement_monetary_policy,
    single_configurator_event,
):
    configurator.set_monetary_policy(
        controller, replacement_monetary_policy, sender=admin
    )

    log = single_configurator_event(configurator, "SetMonetaryPolicy")

    assert log.monetary_policy == replacement_monetary_policy.address


def test_set_monetary_policy_calls_rate_write(configurator, controller, admin):
    rate = 10**12
    new_monetary_policy = boa.loads(
        RATE_WRITE_TRACKING_MONETARY_POLICY, controller.address, rate
    )

    assert new_monetary_policy.rate_write_calls() == 0

    configurator.set_monetary_policy(controller, new_monetary_policy, sender=admin)

    assert controller.monetary_policy() == new_monetary_policy.address
    assert new_monetary_policy.rate_write_calls() == 1


def test_set_monetary_policy_reverts_unauthorized(
    configurator, controller, replacement_monetary_policy
):
    non_admin = boa.env.generate_address("non_admin")

    with boa.reverts("Not authorized for this controller"):
        configurator.set_monetary_policy(
            controller, replacement_monetary_policy, sender=non_admin
        )
