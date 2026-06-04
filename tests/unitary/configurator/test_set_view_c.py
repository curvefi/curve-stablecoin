import boa
import pytest

from tests.utils.constants import ZERO_ADDRESS


@pytest.fixture
def controller_view_blueprint(proto, market_type):
    if market_type == "lending":
        return proto.blueprints.lend_controller_view
    return proto.blueprints.mint_controller_view


def test_set_view_deploys_new_controller_view(
    configurator, controller, controller_view_blueprint, admin
):
    old_view = controller.view()

    configurator.set_view(controller, controller_view_blueprint.address, sender=admin)

    new_view = controller.view()
    assert new_view != ZERO_ADDRESS
    assert new_view != old_view


def test_set_view_emits_set_view(
    configurator,
    controller,
    controller_view_blueprint,
    admin,
    single_configurator_event,
):
    configurator.set_view(controller, controller_view_blueprint.address, sender=admin)

    log = single_configurator_event(configurator, "SetView")

    assert log.controller == controller.address
    assert log.view == controller.view()


def test_set_view_reverts_empty_blueprint(configurator, controller, admin):
    old_view = controller.view()

    with boa.reverts("view blueprint is empty address"):
        configurator.set_view(controller, ZERO_ADDRESS, sender=admin)

    assert controller.view() == old_view


def test_set_view_reverts_unauthorized(
    configurator, controller, controller_view_blueprint
):
    non_admin = boa.env.generate_address("non_admin")
    old_view = controller.view()

    with boa.reverts("Not authorized for this controller"):
        configurator.set_view(
            controller, controller_view_blueprint.address, sender=non_admin
        )

    assert controller.view() == old_view
