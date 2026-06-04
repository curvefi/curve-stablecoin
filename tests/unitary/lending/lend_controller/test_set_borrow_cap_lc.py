import boa
import pytest
from tests.utils import filter_logs


@pytest.mark.parametrize("new_cap", [0, 12345])
def test_default_behavior(controller, configurator, admin, new_cap):
    configurator.set_borrow_cap(controller, new_cap, sender=admin)
    logs = filter_logs(configurator, "SetBorrowCap")
    assert len(logs) == 1 and logs[-1].borrow_cap == new_cap
    assert controller.borrow_cap() == new_cap


def test_set_borrow_cap_non_admin_reverts(controller, configurator):
    with boa.reverts("Not authorized for this controller"):
        configurator.set_borrow_cap(controller, 1)
