import boa
from tests.utils import filter_logs


def test_default_behavior(factory, admin, controller, alice):
    new_fee_receiver = alice
    assert factory.fee_receiver(controller.address) != new_fee_receiver

    with boa.env.prank(admin):
        factory.set_custom_fee_receiver(controller.address, new_fee_receiver)

    logs = filter_logs(factory, "SetFeeReceiver")

    assert factory.fee_receiver(controller.address) == new_fee_receiver

    assert len(logs) == 1
    assert logs[0].controller == controller.address
    assert logs[0].fee_receiver == new_fee_receiver


def test_unauthorized(factory, alice, controller):
    new_fee_receiver = alice
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(alice):
            factory.set_custom_fee_receiver(controller.address, new_fee_receiver)
