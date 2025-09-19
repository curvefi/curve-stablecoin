import boa
import pytest
from tests.utils import filter_logs


@pytest.mark.parametrize("new_cap", [0, 12345])
def test_default_behavior(controller, admin, new_cap):
    controller.set_borrow_cap(new_cap, sender=admin)
    logs = filter_logs(controller, "SetBorrowCap")
    assert len(logs) == 1 and logs[-1].borrow_cap == new_cap
    assert controller.borrow_cap() == new_cap


def test_set_borrow_cap_non_admin_reverts(controller):
    with boa.reverts("only admin"):
        controller.set_borrow_cap(1)
