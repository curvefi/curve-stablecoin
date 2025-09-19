import boa

from tests.utils import max_approve
from tests.utils.constants import MIN_TICKS, WAD

COLLATERAL = 10**21
DEBT = 10**18
RATE = 10**11
TIME_DELTA = 86400
FEE_PCTS = [100, 75, 50, 25, 10]


def test_default_behavior_no_fees(controller):
    assert controller.admin_fees() == 0


def test_default_behavior_with_interest(
    admin,
    controller,
    amm,
    collateral_token,
):
    def outstanding_for_pct(pct: int) -> int:
        with boa.env.anchor():
            controller.set_admin_fee(WAD * pct // 100, sender=admin)
            boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
            max_approve(collateral_token, controller)
            controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

            amm.eval(f"self.rate = {RATE}")
            amm.eval("self.rate_time = block.timestamp")
            boa.env.time_travel(TIME_DELTA)

            return controller.admin_fees()

    base_amount = outstanding_for_pct(100)
    assert base_amount > 0

    results = {100: base_amount}
    for pct in FEE_PCTS[1:]:
        results[pct] = outstanding_for_pct(pct)
        expected = base_amount * pct // 100
        assert results[pct] == expected

    for higher, lower in zip(FEE_PCTS, FEE_PCTS[1:]):
        assert results[higher] > results[lower]
