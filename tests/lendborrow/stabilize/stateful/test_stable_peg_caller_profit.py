import pytest
import boa
from boa.vyper.contract import BoaError
from hypothesis import settings
from hypothesis.stateful import run_state_machine_as_test, invariant
from hypothesis._settings import HealthCheck

from . import base

pytestmark = pytest.mark.usefixtures(
    "add_initial_liquidity",
    "provide_token_to_peg_keepers",
    "mint_alice"
)


class StateMachine(base.StateMachine):
    """
    Stateful test that performs a series of deposits, swaps and withdrawals
    and confirms that profit is calculated right.
    """

    def __init__(self):
        super().__init__(disable_fee=False)

    @invariant()
    def invariant_expected_caller_profit(self):
        """
        Check expected caller profit value.
        """
        for peg_keeper, swap in zip(self.peg_keepers, self.swaps):
            assert swap.fee() > 0
            initial_caller_balance = swap.balanceOf(self.alice)
            expected_caller_profit = peg_keeper.estimate_caller_profit()

            caller_profit = 0
            try:
                with boa.env.prank(self.alice):
                    caller_profit = peg_keeper.update()
            except BoaError as e:
                if 'peg unprofitable' in str(e):
                    continue

            caller_balance = swap.balanceOf(self.alice)
            if caller_profit > 0:  # expected_caller_profit might be 0 in this case
                assert caller_profit == caller_balance - initial_caller_balance
                assert caller_profit >= expected_caller_profit - 1
            else:
                assert expected_caller_profit == 0
                assert caller_balance == initial_caller_balance

            if expected_caller_profit > 0:
                assert caller_profit >= expected_caller_profit - 1


def test_stable_peg(
    add_initial_liquidity,
    swaps,
    peg_keepers,
    redeemable_tokens,
    stablecoin,
    alice,
    receiver,
    admin,
):
    with boa.env.prank(admin):
        for swap in swaps:
            swap.commit_new_fee(4 * 10**7)
        boa.env.time_travel(4 * 86400)
        for swap in swaps:
            swap.apply_new_fee()

    StateMachine.TestCase.settings = settings(max_examples=20, stateful_step_count=40, suppress_health_check=HealthCheck.all())
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    run_state_machine_as_test(StateMachine)


def test_expected_profit_amount(
    add_initial_liquidity,
    swaps,
    peg_keepers,
    redeemable_tokens,
    stablecoin,
    alice,
    receiver,
    admin,
):
    with boa.env.prank(admin):
        for swap in swaps:
            swap.commit_new_fee(4 * 10**7)
        boa.env.time_travel(4 * 86400)
        for swap in swaps:
            swap.apply_new_fee()
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    state = StateMachine()
    state.advance_time()
    state.invariant_expected_caller_profit()
    state.add_coins(amount_0=0.4586551720385922, amount_1=0.2753979563491829, pool_idx=1)
    state.advance_time()
    state.invariant_expected_caller_profit()
    state.remove_imbalance(amount_0=0.2708333333333333, amount_1=6.103515625e-05, pool_idx=1)
    state.advance_time()
    state.invariant_expected_caller_profit()
    state.remove_one_coin(idx=0, pct=0.5, pool_idx=1)
    state.advance_time()
    state.invariant_expected_caller_profit()
    state.remove_imbalance(amount_0=0.5, amount_1=0.0625, pool_idx=0)
    state.advance_time()
    state.invariant_expected_caller_profit()
    state.remove_one_coin(idx=0, pct=0.5, pool_idx=0)
    state.advance_time()
    state.invariant_expected_caller_profit()
    state.add_one_coin(idx=0, pct=0.9, pool_idx=0)
    state.advance_time()
    state.invariant_expected_caller_profit()
    state.teardown()
