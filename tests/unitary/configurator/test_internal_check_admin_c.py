from textwrap import dedent

import boa
import pytest


@pytest.fixture
def deploy_admin_check_configurator(deploy_standalone_configurator):
    def _deploy_admin_check_configurator(default_admin):
        configurator = deploy_standalone_configurator(default_admin)
        configurator.inject_function(
            dedent(
                """
            @external
            def check_admin():
                self._check_admin()
            """
            )
        )
        return configurator

    return _deploy_admin_check_configurator


def test_check_admin_allows_default_admin(deploy_admin_check_configurator):
    default_admin = boa.env.generate_address("default_admin")
    admin_check_configurator = deploy_admin_check_configurator(default_admin)

    with boa.env.prank(default_admin):
        admin_check_configurator.inject.check_admin()


def test_check_admin_reverts_not_admin(deploy_admin_check_configurator):
    default_admin = boa.env.generate_address("default_admin")
    non_admin = boa.env.generate_address("non_admin")
    admin_check_configurator = deploy_admin_check_configurator(default_admin)

    with boa.env.prank(non_admin):
        with boa.reverts("Not admin"):
            admin_check_configurator.inject.check_admin()
