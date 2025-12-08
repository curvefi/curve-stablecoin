def test_default_behavior_no_fees(controller):
    """Naive check to make sure the function is exported, actual test is in the internal tests."""
    assert controller.collect_fees() == 0
