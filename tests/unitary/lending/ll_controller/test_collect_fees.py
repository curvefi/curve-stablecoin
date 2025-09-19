import boa

from tests.utils import max_approve
from tests.utils.constants import MIN_TICKS, WAD

COLLATERAL = 10**21
DEBT = 10**18
RATE = 10**11
TIME_DELTA = 86400
FEE_PCTS = [100, 75, 50, 25, 10]


def test_default_behavior_no_fees(controller):
    assert controller.collected() == 0
    amount = controller.collect_fees()
    assert amount == 0
    assert controller.collected() == 0


def test_collect_fees_accrues_interest(
    admin,
    controller,
    amm,
    collateral_token,
    borrowed_token,
):
    # We iterate over a handful of admin-fee percentages and re-run the same setup for
    # each entry, checking two things: (1) `collect_fees()` returns exactly what ends
    # up in `controller.collected()` and (2) the amount is a linear proportion of the
    # 100% baseline.
    def collect_for_pct(pct: int) -> int:
        with boa.env.anchor():
            controller.set_admin_fee(WAD * pct // 100, sender=admin)
            boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
            max_approve(collateral_token, controller)
            controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

            amm.eval(f"self.rate = {RATE}")
            amm.eval("self.rate_time = block.timestamp")
            boa.env.time_travel(TIME_DELTA)

            boa.deal(borrowed_token, controller.address, 10**24)
            amount = controller.collect_fees()
            assert controller.collected() == amount
            return amount

    base_amount = collect_for_pct(100)
    assert base_amount > 0

    results = {100: base_amount}
    for pct in FEE_PCTS[1:]:
        results[pct] = collect_for_pct(pct)
        expected = base_amount * pct // 100
        assert results[pct] == expected

    for higher, lower in zip(FEE_PCTS, FEE_PCTS[1:]):
        assert results[higher] > results[lower]
