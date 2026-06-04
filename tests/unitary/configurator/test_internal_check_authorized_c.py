from textwrap import dedent

import boa
import pytest

from tests.utils.constants import ZERO_ADDRESS


@pytest.fixture
def deploy_authorization_check_configurator(deploy_standalone_configurator):
    def _deploy_authorization_check_configurator(default_admin):
        configurator = deploy_standalone_configurator(default_admin)
        configurator.inject_function(
            dedent(
                """
            @external
            def check_authorized(_controller: IController):
                self._check_authorized(_controller)
            """
            )
        )
        return configurator

    return _deploy_authorization_check_configurator


def test_check_authorized_allows_default_admin(
    deploy_authorization_check_configurator, get_controller_admin
):
    default_admin = boa.env.generate_address("default_admin")
    controller_address = boa.env.generate_address("controller")
    authorization_check_configurator = deploy_authorization_check_configurator(
        default_admin
    )

    assert (
        get_controller_admin(authorization_check_configurator, controller_address)
        == ZERO_ADDRESS
    )

    with boa.env.prank(default_admin):
        authorization_check_configurator.inject.check_authorized(controller_address)


def test_check_authorized_allows_controller_custom_admin(
    deploy_authorization_check_configurator, get_controller_admin
):
    default_admin = boa.env.generate_address("default_admin")
    custom_admin = boa.env.generate_address("custom_admin")
    controller_address = boa.env.generate_address("controller")
    authorization_check_configurator = deploy_authorization_check_configurator(
        default_admin
    )

    with boa.env.prank(default_admin):
        authorization_check_configurator.set_custom_admin(
            controller_address, custom_admin
        )

    assert (
        get_controller_admin(authorization_check_configurator, controller_address)
        == custom_admin
    )

    with boa.env.prank(custom_admin):
        authorization_check_configurator.inject.check_authorized(controller_address)


def test_check_authorized_reverts_custom_admin_for_other_controller(
    deploy_authorization_check_configurator, get_controller_admin
):
    default_admin = boa.env.generate_address("default_admin")
    custom_admin = boa.env.generate_address("custom_admin")
    controller_address = boa.env.generate_address("controller")
    other_controller_address = boa.env.generate_address("other_controller")
    authorization_check_configurator = deploy_authorization_check_configurator(
        default_admin
    )

    with boa.env.prank(default_admin):
        authorization_check_configurator.set_custom_admin(
            controller_address, custom_admin
        )

    assert (
        get_controller_admin(authorization_check_configurator, controller_address)
        == custom_admin
    )
    assert (
        get_controller_admin(authorization_check_configurator, other_controller_address)
        == ZERO_ADDRESS
    )

    with boa.env.prank(custom_admin):
        with boa.reverts("Not authorized for this controller"):
            authorization_check_configurator.inject.check_authorized(
                other_controller_address
            )


def test_check_authorized_reverts_unconfigured_sender(
    deploy_authorization_check_configurator, get_controller_admin
):
    default_admin = boa.env.generate_address("default_admin")
    non_admin = boa.env.generate_address("non_admin")
    controller_address = boa.env.generate_address("controller")
    authorization_check_configurator = deploy_authorization_check_configurator(
        default_admin
    )

    assert (
        get_controller_admin(authorization_check_configurator, controller_address)
        == ZERO_ADDRESS
    )

    with boa.env.prank(non_admin):
        with boa.reverts("Not authorized for this controller"):
            authorization_check_configurator.inject.check_authorized(controller_address)
