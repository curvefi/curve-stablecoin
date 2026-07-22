"""
Unit/integration tests for curve_stablecoin/price_oracles/v2/OracleFromCurvePools.vy

The oracle chains one or more Curve pool `price_oracle`s into a single
collateral/borrowed price.  Per pool it:
  * detects whether price_oracle needs an index argument (NO_ARGUMENT flag) by
    probing price_oracle(uint256),
  * multiplies the running price by (p_collateral / p_borrowed), where each of
    p_collateral / p_borrowed is 1e18 for coin index 0 (the pool's reference
    coin) or the relevant price_oracle output otherwise.
The constructor calls _price() once as a deploy-time sanity check, so a config
that would make price() revert (bad index on an argument pool, zero borrowed
price) fails at deploy instead.

These tests use inline mock pools (see conftest.py) to cover every branch:
success prices for both price_oracle shapes, both index directions, N>2 pools,
and multi-pool chains; plus every revert site in the constructor and in price().
"""

import boa

from tests.integration.oracle_from_curve_pools.conftest import ONE

P = 2000 * ONE  # generic 2-coin price
Q = 1500 * ONE  # generic no-arg 2-coin price
# 3-coin pool: price_oracle(0) -> coin1, price_oracle(1) -> coin2
P1 = 1500 * ONE
P2 = 30000 * ONE


def ref_price(pools_cfg):
    """Reference re-implementation of OracleFromCurvePools._price()."""
    price = ONE
    for cfg in pools_cfg:
        p_borrowed = ONE
        p_collateral = ONE
        b, c = cfg["borrowed_ix"], cfg["collateral_ix"]
        prices = cfg["prices"]
        if cfg["no_argument"]:
            if c > 0:
                p_collateral = prices[0]
            else:
                p_borrowed = prices[0]
        else:
            if b > 0:
                p_borrowed = prices[b - 1]
            if c > 0:
                p_collateral = prices[c - 1]
        price = price * p_collateral // p_borrowed
    return price


# ===========================================================================
# SUCCESS CASES  (assert the reported price)
# ===========================================================================


def test_single_arg_pool_forward(make_arg_pool, deploy_oracle):
    # 2-coin arg pool, collateral = coin1, borrowed = coin0 (reference).
    pool = make_arg_pool(2, [P])
    oracle = deploy_oracle([pool], [0], [1])

    assert oracle.POOL_COUNT() == 1
    assert oracle.NO_ARGUMENT(0) is False
    # price = 1e18 * price_oracle(0) / 1e18 = P
    assert oracle.price() == P


def test_single_arg_pool_inverse(make_arg_pool, deploy_oracle):
    # Same pool, swapped roles: collateral = coin0, borrowed = coin1.
    pool = make_arg_pool(2, [P])
    oracle = deploy_oracle([pool], [1], [0])

    # price = 1e18 * 1e18 / price_oracle(0) = 1e36 / P
    assert oracle.price() == ONE * ONE // P


def test_single_noarg_pool_forward(make_noarg_pool, deploy_oracle):
    # 2-coin no-argument pool, collateral = coin1.
    pool = make_noarg_pool(Q)
    oracle = deploy_oracle([pool], [0], [1])

    assert oracle.NO_ARGUMENT(0) is True  # detected as argument-less
    assert oracle.price() == Q


def test_single_noarg_pool_inverse(make_noarg_pool, deploy_oracle):
    pool = make_noarg_pool(Q)
    oracle = deploy_oracle([pool], [1], [0])

    assert oracle.NO_ARGUMENT(0) is True
    assert oracle.price() == ONE * ONE // Q


def test_three_coin_pool_collateral_vs_reference(make_arg_pool, deploy_oracle):
    # N>2 pool is always treated as argument-taking (NO_ARGUMENT False).
    pool = make_arg_pool(3, [P1, P2])
    oracle = deploy_oracle([pool], [0], [2])  # collateral = coin2, borrowed = coin0

    assert oracle.NO_ARGUMENT(0) is False
    # price = 1e18 * price_oracle(2-1) / 1e18 = P2
    assert oracle.price() == P2


def test_three_coin_pool_collateral_vs_noncoin0(make_arg_pool, deploy_oracle):
    # Both indexes non-zero: two price_oracle calls.
    pool = make_arg_pool(3, [P1, P2])
    oracle = deploy_oracle([pool], [1], [2])  # borrowed = coin1, collateral = coin2

    # price = 1e18 * price_oracle(1) / price_oracle(0) = P2 / P1 * 1e18
    assert oracle.price() == ONE * P2 // P1


def test_chain_arg_then_noarg(make_arg_pool, make_noarg_pool, deploy_oracle):
    # Two pools of *different* shapes: guards the per-pool NO_ARGUMENT array.
    pool0 = make_arg_pool(3, [P1, P2])  # contributes P2
    pool1 = make_noarg_pool(Q)  # contributes Q
    oracle = deploy_oracle([pool0, pool1], [0, 0], [2, 1])

    assert oracle.POOL_COUNT() == 2
    assert [oracle.NO_ARGUMENT(0), oracle.NO_ARGUMENT(1)] == [False, True]

    cfg = [
        {
            "no_argument": False,
            "borrowed_ix": 0,
            "collateral_ix": 2,
            "prices": [P1, P2],
        },
        {"no_argument": True, "borrowed_ix": 0, "collateral_ix": 1, "prices": [Q]},
    ]
    expected = ref_price(cfg)
    # 30000e18 * 1500e18 / 1e18 = 45_000_000 * 1e18
    assert expected == 45_000_000 * ONE
    assert oracle.price() == expected


def test_chain_inverse_then_forward(make_arg_pool, deploy_oracle):
    # Mixed index directions across the chain.
    pool0 = make_arg_pool(2, [2000 * ONE])  # inverse: borrowed = coin1
    pool1 = make_arg_pool(2, [3000 * ONE])  # forward: collateral = coin1
    oracle = deploy_oracle([pool0, pool1], [1, 0], [0, 1])

    cfg = [
        {
            "no_argument": False,
            "borrowed_ix": 1,
            "collateral_ix": 0,
            "prices": [2000 * ONE],
        },
        {
            "no_argument": False,
            "borrowed_ix": 0,
            "collateral_ix": 1,
            "prices": [3000 * ONE],
        },
    ]
    expected = ref_price(cfg)
    # (1e36 / 2000e18) * 3000e18 / 1e18 = 1.5e18
    assert expected == 15 * ONE // 10
    assert oracle.price() == expected


def test_price_w_matches_price(make_arg_pool, deploy_oracle):
    pool = make_arg_pool(2, [P])
    oracle = deploy_oracle([pool], [0], [1])
    assert oracle.price_w() == oracle.price()


def test_public_config_getters(make_arg_pool, make_noarg_pool, deploy_oracle):
    pool0 = make_arg_pool(3, [P1, P2])
    pool1 = make_noarg_pool(Q)
    oracle = deploy_oracle([pool0, pool1], [0, 1], [2, 0])

    assert oracle.POOL_COUNT() == 2
    assert oracle.POOLS(0) == pool0.address
    assert oracle.POOLS(1) == pool1.address
    assert [oracle.BORROWED_IXS(0), oracle.BORROWED_IXS(1)] == [0, 1]
    assert [oracle.COLLATERAL_IXS(0), oracle.COLLATERAL_IXS(1)] == [2, 0]


# ===========================================================================
# REVERT CASES  (one class per constructor / price() guard)
# ===========================================================================


def test_revert_no_pools(deploy_oracle):
    with boa.reverts("No pools"):
        deploy_oracle([], [], [])


def test_revert_inconsistent_borrowed_len(make_arg_pool, deploy_oracle):
    pool = make_arg_pool(2, [P])
    with boa.reverts("Inconsistent args"):
        deploy_oracle([pool], [0, 1], [1])  # len(borrowed) != len(pools)


def test_revert_inconsistent_collateral_len(make_arg_pool, deploy_oracle):
    pool = make_arg_pool(2, [P])
    with boa.reverts("Inconsistent args"):
        deploy_oracle([pool], [0], [1, 0])  # len(collateral) != len(pools)


def test_revert_borrowed_equals_collateral(make_arg_pool, deploy_oracle):
    pool = make_arg_pool(2, [P])
    with boa.reverts():  # assert borrowed_ixs[i] != collateral_ixs[i]
        deploy_oracle([pool], [1], [1])


def test_revert_borrowed_index_out_of_range(make_arg_pool, deploy_oracle):
    # Arg pool: out-of-range index is caught when the constructor's _price()
    # validation calls price_oracle(1) on a 2-coin pool, which reverts.
    pool = make_arg_pool(2, [P])
    with boa.reverts():
        deploy_oracle([pool], [2], [0])


def test_revert_collateral_index_out_of_range(make_arg_pool, deploy_oracle):
    # Same, on the collateral side.
    pool = make_arg_pool(2, [P])
    with boa.reverts():
        deploy_oracle([pool], [0], [2])


def test_revert_noarg_index_out_of_range(make_noarg_pool, deploy_oracle):
    # No-argument (2-coin) pool: price_oracle() takes no index, so the
    # constructor asserts the coin indexes are 0 or 1 directly.
    pool = make_noarg_pool(Q)
    with boa.reverts("Bad coin index"):
        deploy_oracle([pool], [2], [0])


def test_revert_price_division_by_zero(make_arg_pool, deploy_oracle):
    # borrowed price of 0 -> `_price * p_collateral // p_borrowed` divides by 0,
    # caught at deploy by the constructor's _price() validation.
    pool = make_arg_pool(2, [0])  # price_oracle(0) == 0
    with boa.reverts():
        deploy_oracle([pool], [1], [0])  # borrowed = coin1 -> p_borrowed = 0


def test_revert_zero_price(make_arg_pool, deploy_oracle):
    # collateral price of 0 makes _price() return 0 without any division by
    # zero -> caught only by the constructor's `assert self._price() > 0`.
    pool = make_arg_pool(2, [0])  # price_oracle(0) == 0
    with boa.reverts():
        deploy_oracle([pool], [0], [1])  # collateral = coin1 -> p_collateral = 0
