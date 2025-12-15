def test_default_behavior(blueprint_registry, get_allowed_ids):
    assert get_allowed_ids(blueprint_registry) == ["AMM", "CTR", "VLT", "CTRV"]
