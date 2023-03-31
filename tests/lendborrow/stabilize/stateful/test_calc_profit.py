import pytest
import boa
from boa.vyper.contract import BoaError
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant

pytestmark = pytest.mark.usefixtures(
    "add_initial_liquidity",
    "provide_token_to_peg_keepers",
    "mint_alice"
)


class StateMachine(RuleBasedStateMachine):
    """
    Stateful test that performs a series of deposits, swaps and withdrawals
    and confirms that profit is calculated right.
    """

    st_idx = st.integers(min_value=0, max_value=1)
    st_pct = st.decimals(min_value="0.5", max_value="10000", places=2)
    st_pool = st.integers(min_value=0, max_value=1)  # Only two pools / peg_keepers

    def __init__(self):
        super().__init__()
        self.profit = [pk.calc_profit() for pk in self.peg_keepers]
        stablecoin_decimals = self.stablecoin.decimals()
        self.dmul = [[10 ** r.decimals(), 10 ** stablecoin_decimals] for r in self.redeemable_tokens]

    @rule(idx=st_idx, pct=st_pct, pool_idx=st_pool)
    def add_one_coin(self, idx, pct, pool_idx):
        """
        Add one coin to the pool.
        """
        amounts = [0, 0]
        amounts[idx] = int(self.dmul[pool_idx][idx] * pct)
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].add_liquidity(amounts, 0)

    @rule(amount_0=st_pct, amount_1=st_pct, pool_idx=st_pool)
    def add_coins(self, amount_0, amount_1, pool_idx):
        """
        Add coins to the pool.
        """
        amounts = [
            int(self.dmul[pool_idx][0] * amount_0),
            int(self.dmul[pool_idx][1] * amount_1),
        ]
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].add_liquidity(amounts, 0)

    @rule(idx=st_idx, pct=st_pct, pool_idx=st_pool)
    def remove_one_coin(self, idx, pct, pool_idx):
        """
        Remove liquidity from the pool in only one coin.
        """
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].remove_liquidity_one_coin(int(10**18 * pct), idx, 0)

    @rule(amount_0=st_pct, amount_1=st_pct, pool_idx=st_pool)
    def remove_imbalance(self, amount_0, amount_1, pool_idx):
        """
        Remove liquidity from the pool in an imbalanced manner.
        """
        amounts = [
            int(self.dmul[pool_idx][0] * amount_0),
            int(self.dmul[pool_idx][1] * amount_1),
        ]
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].remove_liquidity_imbalance(
                amounts, 2**256 - 1)

    @rule(pct=st_pct, pool_idx=st_pool)
    def remove(self, pct, pool_idx):
        """
        Remove liquidity from the pool.
        """
        amount = int(10**18 * pct)
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].remove_liquidity(amount, [0] * 2)

    @rule(idx=st_idx, pct=st_pct, pool_idx=st_pool)
    def exchange(self, idx, pct, pool_idx):
        """
        Perform a swap.
        """
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].exchange(idx, 1 - idx, int(self.dmul[pool_idx][idx] * pct), 0)

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
            except BoaError:
                continue

            profit = peg_keeper.calc_profit()
            virtual_price = swap.get_virtual_price()
            aim_profit = (
                swap.balanceOf(peg_keeper) - peg_keeper.debt() * 10**18 // virtual_price
            )
            assert aim_profit >= profit  # Never take more than real profit
            assert aim_profit - profit < 2e18  # Error less than 2 LP Tokens

    @invariant()
    def advance_time(self):
        """
        Advance the clock by 15 minutes between each action.
        Needed for action_delay in Peg Keeper.
        """
        boa.env.time_travel(15 * 60)


def test_profit_increases(
    add_initial_liquidity,
    swaps,
    peg_keepers,
    redeemable_tokens,
    stablecoin,
    alice,
    admin,
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
