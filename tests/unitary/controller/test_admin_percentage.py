from tests.utils.constants import WAD


def test_default_behavior_no_fees(controller, market_type):
    expected_fee = WAD if market_type == "mint" else 0
    assert controller.admin_percentage() == expected_fee
