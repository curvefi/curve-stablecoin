import boa
import pytest


ACTION_DELAY = 15 * 60


pytestmark = pytest.mark.usefixtures("add_initial_liquidity", "provide_token_to_peg_keepers", "mint_bob")


@pytest.mark.parametrize("method", ["provide", "withdraw"])
def test_update_delay(peg_keepers, swaps, redeemable_tokens, stablecoin, bob, peg_keeper_updater, method):
    for pk, swap, rtoken in zip(peg_keepers, swaps, redeemable_tokens):
        with boa.env.anchor():
            with boa.env.prank(bob):
                if method == "provide":
                    swap.add_liquidity([rtoken.balanceOf(bob), 0], 0)
                else:
                    swap.add_liquidity([0, stablecoin.balanceOf(bob)], 0)

            t0 = pk.last_change()
            boa.env.time_travel(ACTION_DELAY + 1)
            with boa.env.prank(peg_keeper_updater):
                pk.update()
            assert pk.last_change() != t0


@pytest.mark.parametrize("method", ["provide", "withdraw"])
def test_update_no_delay(peg_keepers, swaps, redeemable_tokens, stablecoin, bob, peg_keeper_updater, method):
    for pk, swap, rtoken in zip(peg_keepers, swaps, redeemable_tokens):
        with boa.env.anchor():
            with boa.env.prank(bob):
                if method == "provide":
                    swap.add_liquidity([rtoken.balanceOf(bob), 0], 0)
                else:
                    swap.add_liquidity([0, stablecoin.balanceOf(bob)], 0)

            t0 = pk.last_change()
            boa.env.vm.patch.timestamp = t0 + ACTION_DELAY - 30
            with boa.env.prank(peg_keeper_updater):
                pk.update()
            assert pk.last_change() == t0
