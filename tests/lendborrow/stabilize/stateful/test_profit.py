import pytest
import boa
from boa.vyper.contract import BoaError
from hypothesis import settings
from hypothesis.stateful import run_state_machine_as_test, invariant
from hypothesis._settings import HealthCheck

from . import base

pytestmark = pytest.mark.usefixtures(
    "add_initial_liquidity",
    "mint_alice"
)


class StateMachine(base.StateMachine):
    """
    Stateful test that performs a series of deposits, swaps and withdrawals
    and confirms that profit is calculated right.
    """

    @invariant()
    def invariant_profit_increases(self):
        """
        Verify that Peg Keeper profit only increases.
        """
        for i, peg_keeper in enumerate(self.peg_keepers):
            profit = peg_keeper.calc_profit()
            assert profit >= self.profit[i]
            self.profit[i] = profit

    @invariant()
    def invariant_profit(self):
        """
        Check Profit value.
        """
        for peg_keeper, swap in zip(self.peg_keepers, self.swaps):
            try:
                with boa.env.prank(self.alice):
                    peg_keeper.update()
            except BoaError as e:
                if 'peg unprofitable' in str(e):
                    continue

            debt = peg_keeper.debt()
            lp_balance = swap.balanceOf(peg_keeper)
            profit = peg_keeper.calc_profit()
            virtual_price = swap.get_virtual_price()
            aim_profit = lp_balance - debt * 10 ** 18 // virtual_price
            assert 2e18 > aim_profit - profit >= 0
            assert lp_balance * virtual_price - debt * 10 ** 18 >= 0


def test_profit(
    add_initial_liquidity,
    swaps,
    peg_keepers,
    redeemable_tokens,
    stablecoin,
    alice,
    receiver,
    admin,
):
    fee = 4 * 10 ** 7
    with boa.env.prank(admin):
        for swap in swaps:
            swap.commit_new_fee(fee)
        boa.env.time_travel(4 * 86400)
        for swap in swaps:
            swap.apply_new_fee()
    StateMachine.TestCase.settings = settings(max_examples=100, stateful_step_count=40, suppress_health_check=HealthCheck.all())
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    run_state_machine_as_test(StateMachine)


def test_unprofitable_peg(
    add_initial_liquidity,
    swaps,
    peg_keepers,
    redeemable_tokens,
    stablecoin,
    alice,
    receiver,
    admin,
):
    fee = 4 * 10**7
    with boa.env.prank(admin):
        for swap in swaps:
            swap.commit_new_fee(fee)
        boa.env.time_travel(4 * 86400)
        for swap in swaps:
            swap.apply_new_fee()
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    state = StateMachine()
    state.advance_time()
    state.invariant_profit_increases()
    state.invariant_profit()
    state.add_one_coin(idx=0, pct=fee / 10 ** 10, pool_idx=0)
    state.advance_time()
    state.invariant_profit_increases()
    state.invariant_profit()
    state.teardown()
