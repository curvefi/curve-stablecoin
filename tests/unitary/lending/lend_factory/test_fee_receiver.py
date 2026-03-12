import boa
from tests.utils.constants import ZERO_ADDRESS


def test_default_behavior(factory, controller):
    default_receiver = factory.fee_receiver()
    assert default_receiver != ZERO_ADDRESS

    assert factory.fee_receiver(controller.address) == default_receiver

    with boa.env.prank(controller.address):
        assert factory.fee_receiver() == default_receiver


def test_change_default_fee_receiver(factory, admin, controller):
    new_fee_receiver = boa.env.generate_address("new_fee_receiver")
    assert factory.fee_receiver(controller.address) != new_fee_receiver

    with boa.env.prank(admin):
        factory.set_fee_receiver_group_assignee(0, new_fee_receiver)

    assert factory.fee_receiver(controller.address) == new_fee_receiver


def test_custom_behavior(factory, admin, controller):
    default_receiver = factory.fee_receiver(controller.address)
    custom_receiver = boa.env.generate_address("custom_receiver")
    assert default_receiver != custom_receiver

    with boa.env.prank(admin):
        group_id = factory.add_fee_receiver_group(custom_receiver)
        factory.set_fee_receiver_group(controller.address, group_id)

    assert factory.fee_receiver(controller.address) == custom_receiver

    with boa.env.prank(controller.address):
        assert factory.fee_receiver() == custom_receiver

    other_controller = boa.env.generate_address("other_controller")
    assert factory.fee_receiver(other_controller) == default_receiver


def test_set_fee_receiver_group_assignee(factory, admin, controller):
    first_receiver = boa.env.generate_address("first_receiver")
    second_receiver = boa.env.generate_address("second_receiver")

    with boa.env.prank(admin):
        group_id = factory.add_fee_receiver_group(first_receiver)
        factory.set_fee_receiver_group(controller.address, group_id)
        factory.set_fee_receiver_group_assignee(group_id, second_receiver)

    assert factory.fee_receiver(controller.address) == second_receiver


def test_unauthorized_set_fee_receiver_group(factory, controller):
    non_owner = boa.env.generate_address("non_owner")
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(non_owner):
            factory.set_fee_receiver_group(controller.address, 0)


def test_unauthorized_add_fee_receiver_group(factory):
    non_owner = boa.env.generate_address("non_owner")
    candidate_receiver = boa.env.generate_address("candidate_receiver")
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(non_owner):
            factory.add_fee_receiver_group(candidate_receiver)


def test_unauthorized_set_fee_receiver_group_assignee(factory):
    non_owner = boa.env.generate_address("non_owner")
    new_fee_receiver = boa.env.generate_address("new_fee_receiver")
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(non_owner):
            factory.set_fee_receiver_group_assignee(0, new_fee_receiver)
