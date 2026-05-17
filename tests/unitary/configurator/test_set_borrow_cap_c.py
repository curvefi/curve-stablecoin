import boa
import pytest


@pytest.fixture(scope="module")
def market_type():
    return "lending"


def test_set_borrow_cap_updates_lend_controller_borrow_cap(
    configurator, controller, admin
):
    for borrow_cap in (0, 12345):
        configurator.set_borrow_cap(controller, borrow_cap, sender=admin)

        assert controller.borrow_cap() == borrow_cap


def test_set_borrow_cap_emits_set_borrow_cap(
    configurator, controller, admin, single_configurator_event
):
    borrow_cap = 12345

    configurator.set_borrow_cap(controller, borrow_cap, sender=admin)

    log = single_configurator_event(configurator, "SetBorrowCap")

    assert log.borrow_cap == borrow_cap


def test_set_borrow_cap_reverts_unauthorized(configurator, controller):
    non_admin = boa.env.generate_address("non_admin")
    borrow_cap = 12345
    old_borrow_cap = controller.borrow_cap()

    with boa.reverts("Not authorized for this controller"):
        configurator.set_borrow_cap(controller, borrow_cap, sender=non_admin)

    assert controller.borrow_cap() == old_borrow_cap
