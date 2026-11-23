import boa


def test_set_callback_emits_event(
    configurator, controller, admin, single_configurator_event
):
    dummy_callback = boa.env.generate_address("dummy_callback")
    configurator.set_callback(controller, dummy_callback, sender=admin)
    log = single_configurator_event(configurator, "SetCallback")
    assert log.controller == controller.address
    assert log.callback == dummy_callback
