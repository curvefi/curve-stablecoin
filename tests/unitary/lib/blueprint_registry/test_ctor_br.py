def test_default_behavior(blueprint_registry_deployer):
    allowed_ids = ["AMM", "CTR", "VLT", "CTRV"]
    contract = blueprint_registry_deployer(allowed_ids)

    assert contract.get_all_ids() == allowed_ids


def test_ctor_custom_ids(blueprint_registry_deployer):
    allowed_ids = ["A", "B", "C"]
    contract = blueprint_registry_deployer(allowed_ids)

    assert contract.get_all_ids() == allowed_ids
