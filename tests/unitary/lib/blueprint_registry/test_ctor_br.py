def test_default_behavior(blueprint_registry_deployer, get_allowed_ids):
    allowed_ids = ["AMM", "CTR", "VLT", "CTRV"]
    contract = blueprint_registry_deployer(allowed_ids)

    assert get_allowed_ids(contract) == allowed_ids


def test_ctor_custom_ids(blueprint_registry_deployer, get_allowed_ids):
    allowed_ids = ["A", "B", "C"]
    contract = blueprint_registry_deployer(allowed_ids)

    assert get_allowed_ids(contract) == allowed_ids
