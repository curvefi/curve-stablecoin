from tests.utils.constants import MIN_A, MAX_A


def test_min_a(factory):
    assert factory.MIN_A() == MIN_A


def test_max_a(factory):
    assert factory.MAX_A() == MAX_A
