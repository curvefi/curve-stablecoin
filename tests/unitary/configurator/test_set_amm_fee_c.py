import boa

from tests.utils.constants import MIN_AMM_FEE, WAD


def _max_amm_fee(amm):
    return min(WAD * 4 // amm.A(), 10**17)


def test_set_amm_fee_emits_event(
    configurator, controller, admin, single_configurator_event
):
    fee = 10**15  # 0.1%
    configurator.set_amm_fee(controller, fee, sender=admin)
    log = single_configurator_event(configurator, "SetAmmFee")
    assert log.controller == controller.address
    assert log.fee == fee


def test_set_amm_fee_too_low_reverts(configurator, controller, admin):
    with boa.reverts(dev="fee is out of bounds"):
        configurator.set_amm_fee(controller, MIN_AMM_FEE - 1, sender=admin)


def test_set_amm_fee_too_high_reverts(configurator, controller, amm, admin):
    with boa.reverts(dev="fee is out of bounds"):
        configurator.set_amm_fee(controller, _max_amm_fee(amm) + 1, sender=admin)
