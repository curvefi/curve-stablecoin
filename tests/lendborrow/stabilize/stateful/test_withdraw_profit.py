import pytest
import boa
from . import base
from boa.vyper.contract import BoaError
from hypothesis import settings
from hypothesis.stateful import run_state_machine_as_test, rule, invariant

pytestmark = pytest.mark.usefixtures(
    "add_initial_liquidity",
    "provide_token_to_peg_keepers",
    "mint_alice"
)


class StateMachine(base.StateMachine):
    @rule()
    def withdraw_profit(self):
        """
        Withdraw profit from Peg Keeper.
        """
        for peg_keeper, swap in zip(self.peg_keepers, self.swaps):
            profit = peg_keeper.calc_profit()
            receiver_balance = swap.balanceOf(self.receiver)

            returned = peg_keeper.withdraw_profit()

            assert profit == returned
            assert receiver_balance + profit == swap.balanceOf(self.receiver)

    @invariant()
    def invariant_withdraw_profit(self):
        """
        Withdraw profit and check that Peg Keeper is still able to withdraw his debt.
        """
        for peg_keeper, swap, dmul in zip(self.peg_keepers, self.swaps, self.dmul):
            try:
                peg_keeper.update()
            except BoaError:
                continue

            if self.always_withdraw:
                peg_keeper.withdraw_profit()

            with boa.env.anchor():
                if not self.always_withdraw:
                    peg_keeper.withdraw_profit()

                debt = peg_keeper.debt()
                amount = 5 * (debt + 1) + swap.balances(0) * 10**18 // dmul[0] - swap.balances(1)
                if amount < 0:
                    return
                StateMachine._mint(self.alice, [self.stablecoin], [amount])
                with boa.env.prank(self.alice):
                    swap.add_liquidity([0, amount], 0)

                boa.env.time_travel(15 * 60)

                debt_before = peg_keeper.debt()
                try:
                    peg_keeper.update()
                except BoaError:
                    continue
                debt_after = peg_keeper.debt()

                # This is imprecise: probably because decimals of the redeemable token can be not 1e18
                # But could make sense to investigate more
                assert debt_after / debt_before < 1e-5
                assert abs(swap.balances(0) * 10**18 // dmul[0] - (swap.balances(1) - 4 * debt)) <= swap.balances(1) / 1e5


@pytest.mark.parametrize("always_withdraw", [False, True])
def test_withdraw_profit(
    add_initial_liquidity,
    swaps,
    peg_keepers,
    redeemable_tokens,
    stablecoin,
    alice,
    receiver,
    admin,
    always_withdraw,
    _mint
):
    with boa.env.prank(admin):
        for swap in swaps:
            swap.commit_new_fee(4 * 10**7)
        boa.env.time_travel(4 * 86400)
        for swap in swaps:
            swap.apply_new_fee()

    StateMachine.TestCase.settings = settings(max_examples=20, stateful_step_count=40)
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    run_state_machine_as_test(StateMachine)


def test_withdraw_profit_example_1(
    add_initial_liquidity,
    swaps,
    peg_keepers,
    redeemable_tokens,
    stablecoin,
    alice,
    receiver,
    admin,
    _mint
):
    always_withdraw = False

    with boa.env.prank(admin):
        for swap in swaps:
            swap.commit_new_fee(4 * 10**7)
        boa.env.time_travel(4 * 86400)
        for swap in swaps:
            swap.apply_new_fee()

    StateMachine.TestCase.settings = settings(max_examples=20, stateful_step_count=40)
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    state = StateMachine()
    state.advance_time()
    state.invariant_withdraw_profit()
    state.add_one_coin(idx=0, pct=1e-06, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.add_coins(amount_0=0.4500005000000001, amount_1=0.3333333333333333, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.add_coins(amount_0=0.03125, amount_1=1e-06, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_imbalance(amount_0=0.8979001429580658, amount_1=0.9, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_one_coin(idx=0, pct=0.5, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_one_coin(idx=0, pct=0.5, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_one_coin(idx=0, pct=0.8999999999999999, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.add_one_coin(idx=0, pct=0.001953125, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.teardown()
