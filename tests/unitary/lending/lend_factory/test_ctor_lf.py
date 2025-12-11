import boa
from tests.utils.deployers import LENDING_FACTORY_DEPLOYER


def test_ctor(admin, amm_impl, controller_impl, proto):
    amm_blueprint = amm_impl
    controller_blueprint = controller_impl
    vault_blueprint = proto.blueprints.vault
    controller_view_blueprint = proto.blueprints.lend_controller_view

    fee_receiver = boa.env.generate_address("fee_receiver")

    factory = LENDING_FACTORY_DEPLOYER.deploy(
        amm_blueprint,
        controller_blueprint,
        vault_blueprint,
        controller_view_blueprint,
        admin,
        fee_receiver,
    )

    assert factory.amm_blueprint() == amm_blueprint.address
    assert factory.controller_blueprint() == controller_blueprint.address
    assert factory.vault_blueprint() == vault_blueprint.address
    assert factory.controller_view_blueprint() == controller_view_blueprint.address
    assert factory.admin() == admin
    assert factory.default_fee_receiver() == fee_receiver
    assert not factory.paused()
