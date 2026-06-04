import boa
import pytest

from tests.utils.constants import WAD


@pytest.fixture(scope="module")
def market_type():
    return "lending"


def test_set_admin_percentage_updates_lend_controller_admin_percentage(
    configurator, controller, admin
):
    for admin_percentage in (0, WAD // 2, WAD):
        configurator.set_admin_percentage(controller, admin_percentage, sender=admin)

        assert controller.admin_percentage() == admin_percentage


def test_set_admin_percentage_emits_set_admin_percentage(
    configurator, controller, admin, single_configurator_event
):
    admin_percentage = WAD // 2

    configurator.set_admin_percentage(controller, admin_percentage, sender=admin)

    log = single_configurator_event(configurator, "SetAdminPercentage")

    assert log.controller == controller.address
    assert log.admin_percentage == admin_percentage


def test_set_admin_percentage_reverts_above_wad(configurator, controller, admin):
    old_admin_percentage = controller.admin_percentage()

    with boa.reverts("admin percentage higher than 100%"):
        configurator.set_admin_percentage(controller, WAD + 1, sender=admin)

    assert controller.admin_percentage() == old_admin_percentage


def test_set_admin_percentage_reverts_unauthorized(configurator, controller):
    non_admin = boa.env.generate_address("non_admin")
    admin_percentage = WAD // 2
    old_admin_percentage = controller.admin_percentage()

    with boa.reverts("Not authorized for this controller"):
        configurator.set_admin_percentage(
            controller, admin_percentage, sender=non_admin
        )

    assert controller.admin_percentage() == old_admin_percentage
