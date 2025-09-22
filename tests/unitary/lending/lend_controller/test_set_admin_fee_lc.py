import boa
import pytest

from tests.utils import filter_logs
from tests.utils.constants import WAD


@pytest.mark.parametrize("new_fee", [0, WAD // 2])
def test_default_behavior(admin, controller, new_fee):
    controller.set_admin_fee(new_fee, sender=admin)
    logs = filter_logs(controller, "SetAdminFee")
    assert len(logs) == 1 and logs[-1].admin_fee == new_fee
    assert controller.admin_fee() == new_fee


def test_more_than_max(admin, controller):
    with boa.reverts(dev="admin fee higher than 100%"):
        controller.set_admin_fee(WAD + 1, sender=admin)


def test_unauthorized(controller):
    with boa.reverts("only admin"):
        controller.set_admin_fee(1)
