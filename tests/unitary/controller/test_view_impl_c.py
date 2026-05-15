from tests.utils.constants import ZERO_ADDRESS


def test_default_behavior(controller, proto, market_type):
    view = controller.view()
    view_blueprint = (
        proto.blueprints.lend_controller_view
        if market_type == "lending"
        else proto.blueprints.mint_controller_view
    )

    assert view != ZERO_ADDRESS
    assert view != view_blueprint.address
