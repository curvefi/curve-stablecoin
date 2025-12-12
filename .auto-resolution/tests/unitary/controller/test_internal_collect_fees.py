import pytest

import boa

from tests.utils import filter_logs, max_approve
from tests.utils.constants import MIN_TICKS, WAD

COLLATERAL = 10**21
DEBT = 10**18
RATE = 10**11
TIME_DELTA = 86400


@pytest.mark.parametrize("pct", range(1, 101))
def test_default_behavior(
    controller,
    amm,
    borrowed_token,
    collateral_token,
    factory,
    pct,
    market_type,
):
    controller.eval(f"core.admin_percentage = {WAD * pct // 100}")
    boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
    max_approve(collateral_token, controller)
    controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

    amm.eval(f"self.rate = {RATE}")
    amm.eval("self.rate_time = block.timestamp")
    boa.env.time_travel(TIME_DELTA)

    expected_fees = DEBT * TIME_DELTA * RATE // 10**18 * pct // 100

    fee_receiver = factory.fee_receiver()
    receiver_balance_before = borrowed_token.balanceOf(fee_receiver)
    controller_balance_before = borrowed_token.balanceOf(controller)

    amount = controller.collect_fees()

    if pct > 0:
        assert expected_fees > 0
        assert amount > 0
    else:
        assert amount == 0

    logs = filter_logs(controller, "CollectFees")
    assert len(logs) == 1
    assert logs[0].amount == amount
    assert logs[0].new_supply == controller.eval("core._total_debt.initial_debt")

    receiver_balance_after = borrowed_token.balanceOf(fee_receiver)
    controller_balance_after = borrowed_token.balanceOf(controller)
    assert receiver_balance_after - receiver_balance_before == amount
    assert controller_balance_before - controller_balance_after == amount

    assert controller.admin_fees() == 0
    assert controller.eval("core.collected") == amount
    assert amount == expected_fees
