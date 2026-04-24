import boa
from tests.utils import filter_logs


def test_set_callback(amm, controller):
    dummy_callback = boa.env.generate_address("dummy_callback")
    with boa.env.prank(controller.address):
        amm.set_callback(dummy_callback)
    logs = filter_logs(amm, "SetCallback")
    assert len(logs) == 1
    assert logs[0].callback == dummy_callback


def test_set_callback_non_admin_reverts(amm):
    dummy_callback = boa.env.generate_address("dummy_callback")
    with boa.reverts("admin only"):
        amm.set_callback(dummy_callback)
