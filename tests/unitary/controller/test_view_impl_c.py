def test_default_behavior(controller, proto, market_type):
    assert (
        controller.view_impl() == proto.blueprints.lend_controller_view.address
        if market_type == "lending"
        else proto.blueprints.mint_controller_view.address
    )
