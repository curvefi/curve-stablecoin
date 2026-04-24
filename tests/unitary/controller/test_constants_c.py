from tests.utils.constants import MAX_RATE


def test_max_rate(controller):
    assert controller.MAX_RATE() == MAX_RATE
