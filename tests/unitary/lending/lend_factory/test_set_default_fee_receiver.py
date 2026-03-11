import boa


def test_default_behavior(factory, admin, controller):
    new_fee_receiver = boa.env.generate_address("new_fee_receiver")
    assert factory.fee_receiver(controller.address) != new_fee_receiver

    with boa.env.prank(admin):
        factory.set_fee_receiver_group_assignee(0, new_fee_receiver)

    assert factory.fee_receiver(controller.address) == new_fee_receiver


def test_unauthorized(factory):
    non_owner = boa.env.generate_address("non_owner")
    new_fee_receiver = boa.env.generate_address("new_fee_receiver")
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(non_owner):
            factory.set_fee_receiver_group_assignee(0, new_fee_receiver)
