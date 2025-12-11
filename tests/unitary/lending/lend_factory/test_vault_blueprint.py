def test_default_behavior(factory, proto):
    assert factory.vault_blueprint() == proto.blueprints.vault.address
