import boa
import pytest

BORROW_CAP = 5 * 10**18


@pytest.fixture(scope="module")
def borrow_cap():
    return BORROW_CAP


def test_default_behavior(controller, borrow_cap):
    """Test that _on_debt_increased works when called by the controller itself with valid debt amount."""
    debt_amount = BORROW_CAP // 2
    controller._on_debt_increased(debt_amount, sender=controller.address)


def test_unauthorized(controller, alice):
    """Test that _on_debt_increased reverts when called by unauthorized address."""
    debt_amount = 100 * 10**18

    # Should revert when called by non-controller address
    with boa.reverts(dev="virtual method protection"):
        controller._on_debt_increased(debt_amount, sender=alice)


def test_exceed_borrow_cap(controller, borrow_cap):
    """Test that _on_debt_increased reverts when debt exceeds borrow cap."""
    excessive_debt = borrow_cap + 1
    with boa.reverts("Borrow cap exceeded"):
        controller._on_debt_increased(excessive_debt, sender=controller.address)
