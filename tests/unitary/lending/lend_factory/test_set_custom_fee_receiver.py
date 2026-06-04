import boa
from tests.utils import filter_logs


def test_default_behavior(factory, admin, controller):
    new_fee_receiver = boa.env.generate_address("new_fee_receiver")
    assert factory.fee_receiver(controller.address) != new_fee_receiver

    with boa.env.prank(admin):
        factory.set_custom_fee_receiver(controller.address, new_fee_receiver)

    logs = filter_logs(factory, "SetCustomFeeReceiver")

    assert factory.fee_receiver(controller.address) == new_fee_receiver

    assert len(logs) == 1
    assert logs[0].controller == controller.address
    assert logs[0].fee_receiver == new_fee_receiver


def test_unauthorized(factory, controller):
    non_owner = boa.env.generate_address("non_owner")
    new_fee_receiver = boa.env.generate_address("new_fee_receiver")
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(non_owner):
            factory.set_custom_fee_receiver(controller.address, new_fee_receiver)


def test_revert_set_custom_fee_receiver_non_controller(factory, admin):
    new_fee_receiver = boa.env.generate_address("new_fee_receiver")
    non_controller = boa.env.generate_address("non_controller")

    logs_before = filter_logs(factory, "SetCustomFeeReceiver")

    with boa.reverts("not a controller"):
        with boa.env.prank(admin):
            factory.set_custom_fee_receiver(non_controller, new_fee_receiver)

    logs_after = filter_logs(factory, "SetCustomFeeReceiver")
    assert len(logs_after) == len(logs_before)


def test_revert_set_custom_fee_receiver_vault_or_amm(factory, admin, vault, amm):
    new_fee_receiver = boa.env.generate_address("new_fee_receiver")

    with boa.env.prank(admin):
        if vault is not None:
            with boa.reverts("not a controller"):
                factory.set_custom_fee_receiver(vault.address, new_fee_receiver)

        with boa.reverts("not a controller"):
            factory.set_custom_fee_receiver(amm.address, new_fee_receiver)
