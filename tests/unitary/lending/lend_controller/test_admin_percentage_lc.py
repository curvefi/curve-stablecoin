import boa

from tests.utils import max_approve
from tests.utils.constants import MIN_TICKS, WAD

COLLATERAL = 10**21
DEBT = 10**18
RATE = 10**11
TIME_DELTA = 86400


def test_default_behavior_no_fees(controller):
    assert controller.admin_percentage() == 0


def test_default_behavior_with_interest(
    admin,
    controller,
    amm,
    collateral_token,
):
    def outstanding_for_pct(pct: int) -> int:
        with boa.env.anchor():
            controller.set_admin_percentage(WAD * pct // 100, sender=admin)
            boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
            max_approve(collateral_token, controller)
            controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

            amm.eval(f"self.rate = {RATE}")
            amm.eval("self.rate_time = block.timestamp")
            boa.env.time_travel(TIME_DELTA)

            return controller.admin_fees()

    for pct in range(1, 101):
        assert (
            outstanding_for_pct(pct) == DEBT * TIME_DELTA * RATE // 10**18 * pct // 100
        )
