from tests.utils.constants import MAX_UINT256


def test_cap_zero_makes_max_borrowable_zero(controller, admin):
    c_amount = 10**18
    n = 5
    baseline = controller.max_borrowable(c_amount, n)
    assert baseline >= 0  # sanity
    controller.set_borrow_cap(0, sender=admin)
    assert controller.max_borrowable(c_amount, n) == 0


def test_default_behavior_positive_headroom(controller, admin):
    c_amount = 10**24
    n = 5
    controller.set_borrow_cap(0, sender=admin)
    assert controller.max_borrowable(c_amount, n) == 0
    borrowed_balance = controller.borrowed_balance()
    controller.set_borrow_cap(MAX_UINT256, sender=admin)
    # With large collateral, max_borrowable equals the available borrowed balance cap precisely
    assert controller.max_borrowable(c_amount, n) == borrowed_balance
