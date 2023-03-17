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
    def _inner(amount):
        """Amount to add to balances."""
        for rtoken, swap in zip(redeemable_tokens, swaps):
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


# Paused conversion here


# @given(donate_fee=strategy("int", min_value=1, max_value=10**20))
def test_withdraw_profit(
    peg_keeper,
    swap,
    pegged,
    initial_amounts,
    make_profit,
    admin,
    receiver,
    alice,
    peg_keeper_updater,
    balance_change_after_withdraw,
    donate_fee,
    peg_keeper_name,
):
    """Withdraw profit and update for the whole debt."""
    make_profit(donate_fee)

    profit = peg_keeper.calc_profit()
    returned = peg_keeper.withdraw_profit({"from": admin}).return_value
    assert profit == returned
    assert profit == swap.balanceOf(receiver)

    debt = peg_keeper.debt()
    if "meta" in peg_keeper_name:
        amount = 5 * debt + swap.balances(1) * 11 // 10 - swap.balances(0)
    else:
        amount = 5 * debt + swap.balances(1) - swap.balances(0)
    pegged._mint_for_testing(alice, amount, {"from": alice})
    pegged.approve(swap, amount, {"from": alice})
    swap.add_liquidity([amount, 0], 0, {"from": alice})

    assert peg_keeper.update({"from": peg_keeper_updater}).return_value
    balance_change_after_withdraw(5 * debt)


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
