import boa
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant


class StateMachine(RuleBasedStateMachine):
    """
    Base for stateful tests
    """

    st_idx = st.integers(min_value=0, max_value=1)
    st_pct = st.decimals(min_value="0.5", max_value="10000", places=2)
    st_pool = st.integers(min_value=0, max_value=1)  # Only two pools / peg_keepers

    def __init__(self):
        super().__init__()
        self.profit = [pk.calc_profit() for pk in self.peg_keepers]
        stablecoin_decimals = self.stablecoin.decimals()
        self.dmul = [[10 ** r.decimals(), 10 ** stablecoin_decimals] for r in self.redeemable_tokens]
        self.balances = [[swap.balances(0), swap.balances(1)] for swap in self.swaps]

    @rule(idx=st_idx, pct=st_pct, pool_idx=st_pool)
    def add_one_coin(self, idx, pct, pool_idx):
        """
        Add one coin to the pool.
        """
        amounts = [0, 0]
        amounts[idx] = int(self.dmul[pool_idx][idx] * pct)
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].add_liquidity(amounts, 0)
        self.balances[pool_idx][idx] += amounts[idx]

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
        self.balances[pool_idx][0] += amount_0
        self.balances[pool_idx][1] += amount_1

    @rule(idx=st_idx, pct=st_pct, pool_idx=st_pool)
    def remove_one_coin(self, idx, pct, pool_idx):
        """
        Remove liquidity from the pool in only one coin.
        """
        with boa.env.prank(self.alice):
            amount = self.swaps[pool_idx].remove_liquidity_one_coin(int(10**18 * pct), idx, 0)
        self.balances[pool_idx][idx] -= amount

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
        self.balances[pool_idx][0] -= amounts[0]
        self.balances[pool_idx][1] -= amounts[1]

    @rule(pct=st_pct, pool_idx=st_pool)
    def remove(self, pct, pool_idx):
        """
        Remove liquidity from the pool.
        """
        amount = int(10**18 * pct)
        with boa.env.prank(self.alice):
            amounts = self.swaps[pool_idx].remove_liquidity(amount, [0] * 2)
        self.balances[pool_idx][0] -= amounts[0]
        self.balances[pool_idx][1] -= amounts[1]

    @rule(idx=st_idx, pct=st_pct, pool_idx=st_pool)
    def exchange(self, idx, pct, pool_idx):
        """
        Perform a swap.
        """
        amount_in = int(self.dmul[pool_idx][idx] * pct)
        with boa.env.prank(self.alice):
            amount_out = self.swaps[pool_idx].exchange(idx, 1 - idx, amount_in, 0)
        self.balances[pool_idx][idx] += amount_in
        self.balances[pool_idx][idx] -= amount_out

    @invariant()
    def advance_time(self):
        """
        Advance the clock by 15 minutes between each action.
        Needed for action_delay in Peg Keeper.
        """
        boa.env.time_travel(15 * 60)
