def test_default_behavior(factory, amm_impl):
    assert factory.amm_blueprint() == amm_impl.address
