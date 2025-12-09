from tests.utils.constants import WAD

COLLATERAL = 10**21
DEBT = 10**18
RATE = 10**11
TIME_DELTA = 86400


def test_default_behavior_no_fees(controller, market_type):
    expected_fee = WAD if market_type == "mint" else 0
    assert controller.admin_percentage() == expected_fee
