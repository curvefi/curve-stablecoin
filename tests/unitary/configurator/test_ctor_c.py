import boa


def test_ctor_sets_default_admin(deploy_standalone_configurator):
    default_admin = boa.env.generate_address("default_admin")
    standalone_configurator = deploy_standalone_configurator(default_admin)

    assert standalone_configurator.DEFAULT_ADMIN() == default_admin
