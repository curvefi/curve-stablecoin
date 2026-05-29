def test_set_amm_fee_emits_event(
    configurator, controller, admin, single_configurator_event
):
    fee = 10**15  # 0.1%
    configurator.set_amm_fee(controller, fee, sender=admin)
    log = single_configurator_event(configurator, "SetAmmFee")
    assert log.controller == controller.address
    assert log.fee == fee
