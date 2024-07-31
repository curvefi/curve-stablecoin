import pytest
import boa
from . import base
from boa import BoaError
from hypothesis import settings
from hypothesis.stateful import run_state_machine_as_test, rule, invariant

pytestmark = pytest.mark.usefixtures(
    "add_initial_liquidity",
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
                self._disable_fees()
                with boa.env.prank(self.alice):
                    swap.add_liquidity([0, amount], 0)
                self._enable_fees()
                if hasattr(swap, "offpeg_fee_multiplier"):
                    swap.eval("self.offpeg_fee_multiplier = 0")

                boa.env.time_travel(12)

                try:
                    peg_keeper.update()
                except BoaError:
                    continue

                assert peg_keeper.debt() == 0
                assert abs(swap.balances(0) * 10 ** 18 // dmul[0] - (swap.balances(1) - 4 * debt)) <= \
                       debt * swap.fee() // (2 * 10 ** 10)


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
            swap.eval(f"self.fee = {4 * 10 ** 7}")

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
            swap.eval(f"self.fee = {4 * 10 ** 7}")

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


def test_withdraw_profit_example_2(
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
    always_withdraw = True

    with boa.env.prank(admin):
        for swap in swaps:
            swap.eval(f"self.fee = {4 * 10 ** 7}")

    StateMachine.TestCase.settings = settings(max_examples=20, stateful_step_count=40)
    for k, v in locals().items():
        setattr(StateMachine, k, v)
    state = StateMachine()
    state.advance_time()
    state.invariant_withdraw_profit()
    state.exchange(idx=0, pct=0.7168834513258733, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_imbalance(amount_0=0.5202005534658294, amount_1=1e-05, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_imbalance(amount_0=1.0000000000000002e-06, amount_1=6.103515625e-05, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_imbalance(amount_0=1.0000000000000002e-06, amount_1=0.4592796580617876, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.exchange(idx=0, pct=1e-05, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.exchange(idx=0, pct=0.7484680392241835, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_imbalance(amount_0=0.5, amount_1=0.3333333333333333, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_imbalance(amount_0=0.8999999999999999, amount_1=0.5662503294199993, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_imbalance(amount_0=0.19315130644085848, amount_1=0.3333333333333333, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.exchange(idx=0, pct=6.103515625e-05, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.exchange(idx=0, pct=0.8999999999999999, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.exchange(idx=0, pct=6.103515625e-05, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.exchange(idx=0, pct=0.583029819110012, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_imbalance(amount_0=1e-06, amount_1=0.9, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_imbalance(amount_0=6.103515625e-05, amount_1=1e-06, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.remove_imbalance(amount_0=0.6802762567260562, amount_1=0.4585453088794063, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.exchange(idx=1, pct=0.5111175346916537, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.exchange(idx=1, pct=0.9, pool_idx=0)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.exchange(idx=1, pct=0.9, pool_idx=1)
    state.advance_time()
    state.invariant_withdraw_profit()
    state.teardown()
