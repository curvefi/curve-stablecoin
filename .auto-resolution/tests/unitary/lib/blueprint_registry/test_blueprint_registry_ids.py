def test_default_behavior(blueprint_registry):
    ids = blueprint_registry.get_all_ids()
    assert ids == ["AMM", "CTR", "VLT", "CTRV"]
