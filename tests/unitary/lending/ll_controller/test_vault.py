def test_default_behavior(controller, vault):
    assert controller.vault() == vault.address
