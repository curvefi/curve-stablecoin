import pytest
import boa
from tests.utils.deployers import LENDING_FACTORY_DEPLOYER
from tests.utils.constants import ZERO_ADDRESS


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


def test_ctor_reverts_if_fee_receiver_is_zero(admin, amm_impl, controller_impl, proto):
    amm_blueprint = amm_impl
    controller_blueprint = controller_impl
    vault_blueprint = proto.blueprints.vault
    controller_view_blueprint = proto.blueprints.lend_controller_view

    fee_receiver = ZERO_ADDRESS

    with boa.reverts("invalid receiver"):
        LENDING_FACTORY_DEPLOYER.deploy(
            amm_blueprint,
            controller_blueprint,
            vault_blueprint,
            controller_view_blueprint,
            admin,
            fee_receiver,
        )


@pytest.mark.parametrize(
    ("field", "zero_value"),
    [
        ("amm_blueprint", ZERO_ADDRESS),
        ("controller_blueprint", ZERO_ADDRESS),
        ("vault_blueprint", ZERO_ADDRESS),
        ("controller_view_blueprint", ZERO_ADDRESS),
        ("admin", ZERO_ADDRESS),
    ],
)
def test_ctor_reverts_if_required_address_is_zero(
    field, zero_value, admin, amm_impl, controller_impl, proto
):
    args = {
        "amm_blueprint": amm_impl.address,
        "controller_blueprint": controller_impl.address,
        "vault_blueprint": proto.blueprints.vault.address,
        "controller_view_blueprint": proto.blueprints.lend_controller_view.address,
        "admin": admin,
        "fee_receiver": boa.env.generate_address("fee_receiver"),
    }
    args[field] = zero_value

    with boa.reverts():
        LENDING_FACTORY_DEPLOYER.deploy(
            args["amm_blueprint"],
            args["controller_blueprint"],
            args["vault_blueprint"],
            args["controller_view_blueprint"],
            args["admin"],
            args["fee_receiver"],
        )
