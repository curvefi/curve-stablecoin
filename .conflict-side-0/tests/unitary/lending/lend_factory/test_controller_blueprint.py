def test_default_behavior(factory, controller_impl):
    assert factory.controller_blueprint() == controller_impl.address
