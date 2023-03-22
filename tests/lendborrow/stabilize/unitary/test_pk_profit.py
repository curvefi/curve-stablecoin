import boa
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from datetime import timedelta

pytestmark = pytest.mark.usefixtures(
    "add_initial_liquidity",
    "provide_token_to_peg_keepers",
    # "mint_alice",
    # "approve_alice",
)


@pytest.fixture(scope="module")
def make_profit(swaps, redeemable_tokens, stablecoin, alice, admin):
    def _inner(amount, i=None):
        """Amount to add to balances."""
        for j, (rtoken, swap) in enumerate(zip(redeemable_tokens, swaps)):
            if i is not None:
                if j != i:
                    continue
            exchange_amount = amount * 5 // 10**(18 - rtoken.decimals())
            if exchange_amount == 0:
                continue

            with boa.env.prank(admin):
                swap.commit_new_fee(10**9)
                boa.env.time_travel(4 * 86400)
                swap.apply_new_fee()

            with boa.env.prank(alice):
                rtoken._mint_for_testing(alice, exchange_amount)
                rtoken.approve(swap.address, exchange_amount)
                out = swap.exchange(0, 1, exchange_amount, 0)

                stablecoin.approve(swap.address, out)
                swap.exchange(1, 0, out, 0)

            with boa.env.prank(admin):
                swap.commit_new_fee(0)
                boa.env.time_travel(4 * 86400)
                swap.apply_new_fee()

    return _inner


def test_initial_debt(peg_keepers, initial_amounts):
    for peg_keeper, (amount_r, amount_s) in zip(peg_keepers, initial_amounts):
        assert peg_keeper.debt() == amount_s


def test_calc_initial_profit(peg_keepers, swaps):
    """Peg Keeper always generate profit, including first mint."""
    for peg_keeper, swap in zip(peg_keepers, swaps):
        debt = peg_keeper.debt()
        assert debt / swap.get_virtual_price() < swap.balanceOf(peg_keeper)
        aim_profit = swap.balanceOf(peg_keeper) - debt * 10**18 / swap.get_virtual_price()
        assert aim_profit > peg_keeper.calc_profit() > 0


@given(donate_fee=st.integers(min_value=1, max_value=10**20))
@settings(deadline=timedelta(seconds=1000))
def test_calc_profit(peg_keepers, swaps, make_profit, donate_fee):
    make_profit(donate_fee)

    for peg_keeper, swap in zip(peg_keepers, swaps):
        profit = peg_keeper.calc_profit()
        virtual_price = swap.get_virtual_price()
        aim_profit = (
            swap.balanceOf(peg_keeper) - peg_keeper.debt() * 10**18 // virtual_price
        )
        assert aim_profit >= profit  # Never take more than real profit
        assert aim_profit - profit < 2e18  # Error less than 2 LP Tokens


@given(donate_fee=st.integers(min_value=10**14, max_value=10**20))
@settings(deadline=timedelta(seconds=1000))
def test_withdraw_profit(
    peg_keepers,
    swaps,
    stablecoin,
    _mint,
    redeemable_tokens,
    make_profit,
    admin,
    receiver,
    alice,
    peg_keeper_updater,
    donate_fee
):
    """Withdraw profit and update for the whole debt."""

    for i, (peg_keeper, swap, rtoken) in enumerate(zip(peg_keepers, swaps, redeemable_tokens)):
        with boa.env.anchor():
            make_profit(donate_fee, i)
            rtoken_mul = 10 ** (18 - rtoken.decimals())

            profit = peg_keeper.calc_profit()
            with boa.env.prank(admin):
                returned = peg_keeper.withdraw_profit()
                assert profit == returned
                assert profit == swap.balanceOf(receiver)

            debt = peg_keeper.debt()
            amount = 5 * debt + swap.balances(1) - swap.balances(0) * rtoken_mul
            with boa.env.prank(alice):
                _mint(alice, [stablecoin], [amount])
                stablecoin.approve(swap, amount)
                swap.add_liquidity([0, amount], 0)

            with boa.env.prank(peg_keeper_updater):
                assert peg_keeper.update()

            diff = 5 * debt

            assert swap.balances(0) + (diff - diff // 5) // rtoken_mul == swap.balances(1) // rtoken_mul
            assert rtoken.balanceOf(swap.address) + (diff - diff // 5) // rtoken_mul == stablecoin.balanceOf(swap.address) // rtoken_mul


# Paused conversion here


def test_0_after_withdraw(peg_keeper, admin):
    peg_keeper.withdraw_profit({"from": admin})
    assert peg_keeper.calc_profit() == 0


def test_withdraw_profit_access(peg_keeper, alice):
    peg_keeper.withdraw_profit({"from": alice})


def test_event(peg_keeper):
    profit = peg_keeper.calc_profit()
    tx = peg_keeper.withdraw_profit()
    event = tx.events["Profit"]
    assert event["lp_amount"] == profit


# @pytest.mark.parametrize("coin_to_imbalance", [0, 1])
def test_profit_receiver(
    swap, peg_keeper, bob, receiver, coin_to_imbalance, imbalance_pool
):
    imbalance_pool(coin_to_imbalance)
    peg_keeper.update(receiver, {"from": bob})
    assert swap.balanceOf(bob) == 0
    assert swap.balanceOf(receiver) > 0


def test_unprofitable_peg(
    swap, decimals, pegged, peg_keeper, alice, imbalance_pool, set_fees, chain
):
    # Leave a little of debt
    little = 10 * 10 ** decimals[0]
    imbalance_pool(0, 5 * (peg_keeper.debt() - little))
    peg_keeper.update({"from": alice})

    # Imbalance so it should give all
    able_to_add = pegged.balanceOf(peg_keeper)
    imbalance_pool(1, 5 * able_to_add, add_diff=True)

    set_fees(10**9)

    with boa.reverts():  # dev: peg was unprofitable
        chain.sleep(15 * 60)
        peg_keeper.update({"from": alice})


# @given(share=strategy("int", min_value=0, max_value=10**5))
# @pytest.mark.parametrize("coin_to_imbalance", [0, 1])
def test_profit_share(
    peg_keeper, swap, bob, admin, coin_to_imbalance, imbalance_pool, share
):
    peg_keeper.set_new_caller_share(share, {"from": admin})
    imbalance_pool(coin_to_imbalance)

    profit_before = peg_keeper.calc_profit()
    peg_keeper.update({"from": bob})
    profit_after = peg_keeper.calc_profit()

    receiver_profit = profit_after - profit_before
    caller_profit = swap.balanceOf(bob)

    assert caller_profit == (receiver_profit + caller_profit) * share // 10**5
