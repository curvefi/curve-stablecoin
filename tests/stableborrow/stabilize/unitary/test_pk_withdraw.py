import boa
import pytest
from hypothesis import given
from hypothesis import strategies as st

pytestmark = pytest.mark.usefixtures(
    "add_initial_liquidity",
    "provide_token_to_peg_keepers",
    "mint_alice",
)


@given(amount=st.integers(min_value=10**20, max_value=10**24))
def test_withdraw(
    swaps,
    alice,
    amount,
    peg_keepers,
    peg_keeper_updater,
):
    for swap, peg_keeper in zip(swaps, peg_keepers):
        with boa.env.prank(alice):
            swap.add_liquidity([0, amount], 0)
        balances = [swap.balances(0), swap.balances(1)]

        with boa.env.prank(peg_keeper_updater):
            assert peg_keeper.update()

        new_balances = [swap.balances(0), swap.balances(1)]
        assert new_balances[0] == balances[0]
        assert new_balances[1] == balances[1] - amount // 5


def test_withdraw_insufficient_debt(
    swaps,
    stablecoin,
    alice,
    initial_amounts,
    peg_keepers,
    peg_keeper_updater,
    _mint,
):
    """Provide 10x of pegged, so Peg Keeper can't withdraw the whole 1/5 part."""
    for swap, peg_keeper, initial in zip(swaps, peg_keepers, initial_amounts):
        amount = 10 * initial[1]
        _mint(alice, [stablecoin], [amount])
        with boa.env.prank(alice):
            swap.add_liquidity([0, amount], 0)
        balances = [swap.balances(0), swap.balances(1)]

        with boa.env.prank(peg_keeper_updater):
            assert peg_keeper.update()

        new_balances = [swap.balances(0), swap.balances(1)]
        assert new_balances[0] == balances[0]
        assert balances[1] > new_balances[1] > balances[1] - amount // 5


def test_withdraw_dust_debt(
    swaps,
    stablecoin,
    alice,
    initial_amounts,
    redeemable_tokens,
    peg_keepers,
    peg_keeper_updater,
    _mint
):
    for swap, peg_keeper, initial, rtoken in zip(swaps, peg_keepers, initial_amounts, redeemable_tokens):
        rtoken_mul = 10 ** (18 - rtoken.decimals())
        amount = 5 * (initial[1] - 1)
        _mint(alice, [stablecoin], [2 * amount])

        # Peg Keeper withdraws almost all debt
        with boa.env.prank(alice):
            swap.add_liquidity([0, amount], 0)
        with boa.env.prank(peg_keeper_updater):
            assert peg_keeper.update()

        assert (swap.balances(1) - (amount - amount // 5)) // rtoken_mul == swap.balances(0)

        remove_amount = swap.balances(1) - swap.balances(0) * rtoken_mul
        with boa.env.prank(alice):
            swap.remove_liquidity_imbalance([0, remove_amount], 2**256 - 1)
        assert swap.balances(0) == swap.balances(1) // rtoken_mul

        # Does not withdraw anything
        with boa.env.prank(alice):
            swap.add_liquidity([0, amount], 0)
        with boa.env.prank(peg_keeper_updater):
            assert not peg_keeper.update()


def test_almost_balanced(
    swaps,
    alice,
    admin,
    peg_keepers,
    peg_keeper_updater
):
    for swap, peg_keeper in zip(swaps, peg_keepers):
        with boa.env.prank(alice):
            swap.add_liquidity([0, 10**18], 0)
        with boa.env.prank(admin):
            swap.commit_new_fee(10**6)
            boa.env.time_travel(4 * 86400)
            swap.apply_new_fee()
        with boa.reverts():  # dev: peg was unprofitable
            with boa.env.prank(peg_keeper_updater):
                peg_keeper.update()
