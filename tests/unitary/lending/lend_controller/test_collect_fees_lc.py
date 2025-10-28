import boa

from tests.utils import max_approve
from tests.utils.constants import MIN_TICKS, WAD

COLLATERAL = 10**21
DEBT = 10**18
RATE = 10**11
TIME_DELTA = 86400


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
    def collect_for_pct(pct: int) -> int:
        with boa.env.anchor():
            controller.set_admin_percentage(WAD * pct // 100, sender=admin)
            boa.deal(collateral_token, boa.env.eoa, COLLATERAL)
            max_approve(collateral_token, controller)
            controller.create_loan(COLLATERAL, DEBT, MIN_TICKS)

            amm.eval(f"self.rate = {RATE}")
            amm.eval("self.rate_time = block.timestamp")
            boa.env.time_travel(TIME_DELTA)

            expected = controller.admin_fees()
            amount = controller.collect_fees()
            assert controller.collected() == amount == expected

            return amount

    for pct in range(1, 101):
        assert collect_for_pct(pct) == DEBT * TIME_DELTA * RATE // 10**18 * pct // 100


def test_collect_fees_reverts_if_not_enough_balance(
    admin,
    controller,
    amm,
    collateral_token,
    borrowed_token,
):
    controller.set_admin_percentage(WAD, sender=admin)
    debt = controller.available_balance()
    collateral = 10 * debt * amm.price_oracle() // 10**18
    boa.deal(collateral_token, boa.env.eoa, collateral)
    max_approve(collateral_token, controller)
    max_approve(borrowed_token, controller)
    controller.create_loan(collateral, debt, MIN_TICKS)

    amm.eval(f"self.rate = {RATE}")
    amm.eval("self.rate_time = block.timestamp")
    boa.env.time_travel(TIME_DELTA)

    expected = controller.admin_fees()
    assert expected > 0
    with boa.reverts():
        controller.collect_fees()
    controller.repay(expected)
    amount = controller.collect_fees()
    assert controller.collected() == amount == expected
