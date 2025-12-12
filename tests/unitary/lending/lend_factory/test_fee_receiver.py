import boa
from tests.utils.constants import ZERO_ADDRESS


def test_default_behavior_default_receiver(factory, controller):
    default_receiver = factory.default_fee_receiver()
    assert default_receiver != ZERO_ADDRESS

    # Check via explicit argument
    assert factory.fee_receiver(controller.address) == default_receiver

    # Check via default argument (msg.sender)
    with boa.env.prank(controller.address):
        assert factory.fee_receiver() == default_receiver


def test_default_behavior_custom_receiver(factory, admin, controller):
    default_receiver = factory.default_fee_receiver()
    custom_receiver = boa.env.generate_address("custom_receiver")
    assert default_receiver != custom_receiver

    with boa.env.prank(admin):
        factory.set_custom_fee_receiver(controller.address, custom_receiver)

    # Check custom receiver is returned for specific controller
    assert factory.fee_receiver(controller.address) == custom_receiver

    # Check custom receiver is returned when calling as controller (default arg)
    with boa.env.prank(controller.address):
        assert factory.fee_receiver() == custom_receiver

    # Check default receiver is still returned for other controllers
    other_controller = boa.env.generate_address("other_controller")
    assert factory.fee_receiver(other_controller) == default_receiver
