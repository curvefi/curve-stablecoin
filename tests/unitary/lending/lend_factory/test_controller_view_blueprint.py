def test_default_behavior(factory, proto):
    assert factory.controller_view_blueprint() == proto.blueprints.lend_controller_view.address
