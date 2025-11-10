import boa


def test_default_behavior(controller, borrow_cap):
    """Test that _on_debt_increased works when called by the controller itself with valid debt amount."""
    debt_amount = borrow_cap // 2
    delta = int(borrow_cap * 0.1)
    controller._on_debt_increased(delta, debt_amount, sender=controller.address)


def test_unauthorized(controller, borrow_cap):
    """Test that _on_debt_increased reverts when called by unauthorized address."""
    debt_amount = borrow_cap // 2
    delta = int(borrow_cap * 0.1)

    # Should revert when called by non-controller address
    with boa.reverts(dev="virtual method protection"):
        controller._on_debt_increased(delta, debt_amount)


def test_exceed_borrow_cap(controller, borrow_cap):
    """Test that _on_debt_increased reverts when debt exceeds borrow cap."""
    excessive_debt = borrow_cap + 1
    delta = int(borrow_cap * 0.1)
    with boa.reverts("Borrow cap exceeded"):
        controller._on_debt_increased(delta, excessive_debt, sender=controller.address)


def test_exceed_available_balance(controller, borrow_cap):
    debt_amount = borrow_cap // 2
    delta = controller.available_balance() + 1

    with boa.reverts("Available balance exceeded"):
        controller._on_debt_increased(delta, debt_amount, sender=controller.address)
