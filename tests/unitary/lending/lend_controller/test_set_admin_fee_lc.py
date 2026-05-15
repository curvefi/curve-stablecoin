import boa
import pytest

from tests.utils import filter_logs
from tests.utils.constants import WAD


@pytest.mark.parametrize("new_fee", [0, WAD // 2])
def test_default_behavior(admin, controller, configurator, new_fee):
    configurator.set_admin_percentage(controller, new_fee, sender=admin)
    logs = filter_logs(configurator, "SetAdminPercentage")
    assert len(logs) == 1 and logs[-1].admin_percentage == new_fee
    assert controller.admin_percentage() == new_fee


def test_more_than_max(admin, controller, configurator):
    with boa.reverts("admin percentage higher than 100%"):
        configurator.set_admin_percentage(controller, WAD + 1, sender=admin)


def test_unauthorized(controller, configurator):
    with boa.reverts("Not authorized for this controller"):
        configurator.set_admin_percentage(controller, 1)
