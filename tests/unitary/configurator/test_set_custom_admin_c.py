import boa

from tests.utils.constants import ZERO_ADDRESS


def test_set_custom_admin_updates_admin_storage(
    deploy_standalone_configurator, get_controller_admin
):
    default_admin = boa.env.generate_address("default_admin")
    controller_address = boa.env.generate_address("controller")
    custom_admin = boa.env.generate_address("custom_admin")
    standalone_configurator = deploy_standalone_configurator(default_admin)

    standalone_configurator.set_custom_admin(
        controller_address, custom_admin, sender=default_admin
    )

    assert (
        get_controller_admin(standalone_configurator, controller_address)
        == custom_admin
    )


def test_set_custom_admin_emits_set_custom_admin(
    deploy_standalone_configurator,
    single_configurator_event,
):
    default_admin = boa.env.generate_address("default_admin")
    controller_address = boa.env.generate_address("controller")
    custom_admin = boa.env.generate_address("custom_admin")
    standalone_configurator = deploy_standalone_configurator(default_admin)

    standalone_configurator.set_custom_admin(
        controller_address, custom_admin, sender=default_admin
    )

    log = single_configurator_event(standalone_configurator, "SetCustomAdmin")

    assert log.controller == controller_address
    assert log.admin == custom_admin


def test_set_custom_admin_reverts_not_admin(
    deploy_standalone_configurator,
):
    default_admin = boa.env.generate_address("default_admin")
    non_admin = boa.env.generate_address("non_admin")
    controller_address = boa.env.generate_address("controller")
    custom_admin = boa.env.generate_address("custom_admin")
    standalone_configurator = deploy_standalone_configurator(default_admin)

    with boa.reverts("Not admin"):
        standalone_configurator.set_custom_admin(
            controller_address, custom_admin, sender=non_admin
        )


def test_set_custom_admin_zero_admin_resets_controller_admin(
    deploy_standalone_configurator, get_controller_admin
):
    default_admin = boa.env.generate_address("default_admin")
    controller_address = boa.env.generate_address("controller")
    custom_admin = boa.env.generate_address("custom_admin")
    standalone_configurator = deploy_standalone_configurator(default_admin)

    standalone_configurator.set_custom_admin(
        controller_address, custom_admin, sender=default_admin
    )
    standalone_configurator.set_custom_admin(
        controller_address, ZERO_ADDRESS, sender=default_admin
    )

    assert (
        get_controller_admin(standalone_configurator, controller_address)
        == ZERO_ADDRESS
    )

    with boa.env.prank(custom_admin):
        with boa.reverts("Not authorized for this controller"):
            standalone_configurator.set_amm_fee(controller_address, 0)
