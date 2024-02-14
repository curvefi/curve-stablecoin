import boa
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant
from boa.vyper.contract import BoaError
from ..conftest import BASE_AMOUNT


class StateMachine(RuleBasedStateMachine):
    """
    Base for stateful tests
    """

    st_idx = st.integers(min_value=0, max_value=1)
    st_pct = st.floats(min_value=1e-6, max_value=0.9)
    st_pool = st.integers(min_value=0, max_value=1)  # Only two pools / peg_keepers

    def __init__(self):
        super().__init__()
        self.profit = [pk.calc_profit() for pk in self.peg_keepers]
        stablecoin_decimals = self.stablecoin.decimals()
        self.dmul = [[10 ** r.decimals(), 10 ** stablecoin_decimals] for r in self.redeemable_tokens]

    def _disable_fees(self):
        self.fees = []
        with boa.env.prank(self.admin):
            for swap in self.swaps:
                self.fees.append(swap.fee())
                swap.commit_new_fee(0)
            boa.env.time_travel(7 * 86400)
            for swap in self.swaps:
                swap.apply_new_fee()

    def _enable_fees(self):
        with boa.env.prank(self.admin):
            for swap, fee in zip(self.swaps, self.fees):
                swap.commit_new_fee(fee)
            boa.env.time_travel(7 * 86400)
            for swap in self.swaps:
                swap.apply_new_fee()

    @rule(idx=st_idx, pct=st_pct, pool_idx=st_pool)
    def add_one_coin(self, idx, pct, pool_idx):
        """
        Add one coin to the pool.
        """
        amounts = [0, 0]
        amounts[idx] = int(self.dmul[pool_idx][idx] * BASE_AMOUNT * pct)
        coins = [self.redeemable_tokens[pool_idx], self.stablecoin]
        if coins[idx].balanceOf(self.alice) < amounts[idx]:
            return
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].add_liquidity(amounts, 0)

    @rule(amount_0=st_pct, amount_1=st_pct, pool_idx=st_pool)
    def add_coins(self, amount_0, amount_1, pool_idx):
        """
        Add coins to the pool.
        """
        amounts = [
            int(self.dmul[pool_idx][0] * BASE_AMOUNT * amount_0),
            int(self.dmul[pool_idx][1] * BASE_AMOUNT * amount_1),
        ]
        coins = [self.redeemable_tokens[pool_idx], self.stablecoin]
        for idx in [0, 1]:
            if coins[idx].balanceOf(self.alice) < amounts[idx]:
                return
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].add_liquidity(amounts, 0)

    @rule(idx=st_idx, pct=st_pct, pool_idx=st_pool)
    def remove_one_coin(self, idx, pct, pool_idx):
        """
        Remove liquidity from the pool in only one coin.
        """
        supply = self.swaps[pool_idx].balanceOf(self.alice)
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].remove_liquidity_one_coin(int(supply * pct), idx, 0)

    @rule(amount_0=st_pct, amount_1=st_pct, pool_idx=st_pool)
    def remove_imbalance(self, amount_0, amount_1, pool_idx):
        """
        Remove liquidity from the pool in an imbalanced manner.
        """
        amounts = [
            int(self.dmul[pool_idx][0] * BASE_AMOUNT * amount_0),
            int(self.dmul[pool_idx][1] * BASE_AMOUNT * amount_1),
        ]
        for i in range(2):
            if amounts[i] > self.swaps[pool_idx].balances(i):
                # Don't remove more than we have
                return
        try:
            token_amount = self.swaps[pool_idx].calc_token_amount(amounts, False)
        except BoaError:
            # Most likely we want to withdraw more than the pool has
            return

        if token_amount > self.swaps[pool_idx].balanceOf(self.alice):
            return
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].remove_liquidity_imbalance(
                amounts, 2**256 - 1)

    @rule(pct=st_pct, pool_idx=st_pool)
    def remove(self, pct, pool_idx):
        """
        Remove liquidity from the pool.
        """
        amount = int(self.swaps[pool_idx].balanceOf(self.alice) * pct)
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].remove_liquidity(amount, [0] * 2)

    @rule(idx=st_idx, pct=st_pct, pool_idx=st_pool)
    def exchange(self, idx, pct, pool_idx):
        """
        Perform a swap.
        """
        amount_in = int(self.dmul[pool_idx][idx] * BASE_AMOUNT * pct)
        coins = [self.redeemable_tokens[pool_idx], self.stablecoin]
        if coins[idx].balanceOf(self.alice) < amount_in:
            return
        with boa.env.prank(self.alice):
            self.swaps[pool_idx].exchange(idx, 1 - idx, amount_in, 0)

    @invariant()
    def advance_time(self):
        """
        Advance the clock by 15 minutes between each action.
        Needed for action_delay in Peg Keeper.
        """
        boa.env.time_travel(15 * 60)
