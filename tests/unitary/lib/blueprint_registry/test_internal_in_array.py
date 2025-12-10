import boa

def test_default_behavior_found(blueprint_registry):
    assert blueprint_registry.in_array("AMM", ["AMM", "CTR", "VLT", "CTRV"])
    assert blueprint_registry.in_array("CTR", ["AMM", "CTR", "VLT", "CTRV"])
    assert blueprint_registry.in_array("VLT", ["AMM", "CTR", "VLT", "CTRV"])
    assert blueprint_registry.in_array("CTRV", ["AMM", "CTR", "VLT", "CTRV"])

def test_default_behavior_not_found(blueprint_registry):
    assert not blueprint_registry.in_array("XXXX", ["AMM", "CTR", "VLT", "CTRV"])
    assert not blueprint_registry.in_array("AMM", ["CTR", "VLT", "CTRV"])
