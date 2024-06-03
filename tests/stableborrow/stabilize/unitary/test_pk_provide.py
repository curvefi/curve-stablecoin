import boa
import pytest
from hypothesis import given
from hypothesis import strategies as st

pytestmark = pytest.mark.usefixtures(
    "add_initial_liquidity",
    "mint_alice",
)


@given(amount=st.integers(min_value=10**20, max_value=10**24))
def test_provide(
    swaps,
    redeemable_tokens,
    stablecoin,
    alice,
    amount,
    peg_keepers,
    peg_keeper_updater
):
    for swap, rtoken, peg_keeper in zip(swaps, redeemable_tokens, peg_keepers):
        rtoken_mul = 10 ** (18 - rtoken.decimals())
        ramount = amount // rtoken_mul
        with boa.env.prank(alice):
            swap.add_liquidity([ramount, 0], 0)
        balances = [swap.balances(0), swap.balances(1)]

        with boa.env.prank(peg_keeper_updater):
            peg_keeper.update()

        new_balances = [swap.balances(0), swap.balances(1)]
        assert new_balances[0] == balances[0]
        assert (new_balances[1]) // rtoken_mul == (balances[1] + amount // 5) // rtoken_mul


def test_min_coin_amount(swaps, initial_amounts, alice, peg_keepers, peg_keeper_updater):
    for swap, peg_keeper, initial in zip(swaps, peg_keepers, initial_amounts):
        with boa.env.prank(alice):
            swap.add_liquidity([initial[0], 0], 0)
        with boa.env.prank(peg_keeper_updater):
            assert peg_keeper.update()


def test_almost_balanced(swaps, alice, peg_keepers, peg_keeper_updater, redeemable_tokens, stablecoin):
    for swap, peg_keeper, rtoken in zip(swaps, peg_keepers, redeemable_tokens):
        with boa.env.prank(alice):
            diff = swap.balances(1) * 10 ** (18 - stablecoin.decimals()) -\
                   swap.balances(0) * 10 ** (18 - rtoken.decimals())
            amounts = [diff if diff > 0 else 0, -diff if diff < 0 else 0]
            amounts[0] += 10
            swap.add_liquidity(amounts, 0)
        with boa.reverts('peg unprofitable'):  # dev: peg was unprofitable
            with boa.env.prank(peg_keeper_updater):
                peg_keeper.update()
