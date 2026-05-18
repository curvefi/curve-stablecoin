import boa
from tests.utils import filter_logs
from tests.utils.constants import MAX_UINT256

WEEK = 7 * 86400


def _create_loan(collateral_token, controller, name="events_borrower"):
    borrower = boa.env.generate_address(name)
    boa.deal(collateral_token, borrower, 10**21)
    collateral_token.approve(controller, MAX_UINT256, sender=borrower)
    boa.env.time_travel(seconds=2 * WEEK + 5)
    controller.create_loan(10**21, 10**21 * 2600, 10, sender=borrower)
    return borrower


def test_checkpoint_rpc(collateral_token, controller, lm_callback):
    with boa.env.anchor():
        borrower = _create_loan(collateral_token, controller)
        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(borrower, sender=borrower)

        logs = filter_logs(lm_callback, "CheckpointRPC")
        i_rpc = lm_callback.I_rpc()
        assert len(logs) == 1
        assert logs[0].rpc == i_rpc[0]
        assert logs[0].t == i_rpc[1]


def test_checkpoint_band(collateral_token, controller, amm, lm_callback):
    with boa.env.anchor():
        borrower = _create_loan(collateral_token, controller)
        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(borrower, sender=borrower)

        logs = filter_logs(lm_callback, "CheckpointBand")
        ns = amm.read_user_tick_numbers(borrower)
        n_bands = ns[1] - ns[0] + 1
        assert len(logs) == n_bands
        for log in logs:
            assert log.rps == lm_callback.I_rps(log.n)[0]
            assert log.collateral_per_share == lm_callback.collateral_per_share(log.n)


def test_checkpoint_user(collateral_token, controller, lm_callback):
    with boa.env.anchor():
        borrower = _create_loan(collateral_token, controller)
        boa.env.time_travel(WEEK)
        lm_callback.user_checkpoint(borrower, sender=borrower)

        logs = filter_logs(lm_callback, "CheckpointUser")
        assert len(logs) == 1
        assert logs[0].user == borrower
        assert logs[0].integrate_fraction == lm_callback.integrate_fraction(borrower)


def test_update_inflation_rate(collateral_token, controller, lm_callback):
    with boa.env.anchor():
        borrower = _create_loan(collateral_token, controller)
        future_epoch = lm_callback.future_epoch_time()
        boa.env.time_travel(seconds=future_epoch - boa.env.timestamp + 1)
        lm_callback.user_checkpoint(borrower, sender=borrower)

        logs = filter_logs(lm_callback, "UpdateInflationRate")
        assert len(logs) == 1
        assert logs[0].new_rate == lm_callback.inflation_rate()
        assert logs[0].future_epoch_time == lm_callback.future_epoch_time()


def test_set_killed(admin, lm_callback):
    with boa.env.anchor():
        lm_callback.set_killed(True, sender=admin)
        logs = filter_logs(lm_callback, "SetKilled")
        assert len(logs) == 1
        assert logs[0].is_killed is True

        lm_callback.set_killed(False, sender=admin)
        logs = filter_logs(lm_callback, "SetKilled")
        assert len(logs) == 1
        assert logs[0].is_killed is False
