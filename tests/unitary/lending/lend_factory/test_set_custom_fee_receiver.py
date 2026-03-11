import boa


def test_default_behavior(factory, admin, controller):
    new_fee_receiver = boa.env.generate_address("new_fee_receiver")
    assert factory.fee_receiver(controller.address) != new_fee_receiver

    with boa.env.prank(admin):
        group_id = factory.add_fee_receiver_group(new_fee_receiver)
        factory.set_fee_receiver_group(controller.address, group_id)

    assert factory.fee_receiver(controller.address) == new_fee_receiver

def test_unauthorized(factory, controller):
    non_owner = boa.env.generate_address("non_owner")
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(non_owner):
            factory.set_fee_receiver_group(controller.address, 0)


def test_set_fee_receiver_group_assignee(factory, admin, controller):
    first_receiver = boa.env.generate_address("first_receiver")
    new_fee_receiver = boa.env.generate_address("new_fee_receiver")

    with boa.env.prank(admin):
        group_id = factory.add_fee_receiver_group(first_receiver)
        factory.set_fee_receiver_group(controller.address, group_id)
        factory.set_fee_receiver_group_assignee(group_id, new_fee_receiver)

    assert factory.fee_receiver(controller.address) == new_fee_receiver
