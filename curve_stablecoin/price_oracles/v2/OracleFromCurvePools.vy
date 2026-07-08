#pragma version 0.4.3
"""
@title OracleFromCurvePools
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice The oracle chains multiple Curve pools oracles. If there are stablepools with stored_rates in the chain - they are ignored,
        and all the prices in the chain are for underlying coins of such pools.
"""

from curve_stablecoin.interfaces import IPriceOracle

implements: IPriceOracle


interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def coins(i: uint256) -> address: view


MAX_COINS: constant(uint256) = 8
MAX_POOLS: constant(uint256) = 8

POOLS: public(immutable(DynArray[Pool, MAX_POOLS]))
BORROWED_IXS: public(immutable(DynArray[uint256, MAX_POOLS]))
COLLATERAL_IXS: public(immutable(DynArray[uint256, MAX_POOLS]))
NO_ARGUMENT: public(immutable(DynArray[bool, MAX_POOLS]))
POOL_COUNT: public(immutable(uint256))


@deploy
def __init__(
        _pools: DynArray[Pool, MAX_POOLS],
        _borrowed_ixs: DynArray[uint256, MAX_POOLS],
        _collateral_ixs: DynArray[uint256, MAX_POOLS]
    ):
    """
    @notice Configure the chain of Curve pools to price through.
    @dev The coin count of each pool is auto-detected, as is whether its
         `price_oracle` takes a coin-index argument (recorded in NO_ARGUMENT).
    @param _pools Curve pools to chain, in order (1 to MAX_POOLS).
    @param _borrowed_ixs For each pool, the coin index of the borrowed-side token.
    @param _collateral_ixs For each pool, the coin index of the collateral-side token.
    """
    POOLS = _pools
    POOL_COUNT = len(_pools)
    assert POOL_COUNT > 0, "No pools"
    assert POOL_COUNT == len(_borrowed_ixs) and POOL_COUNT == len(_collateral_ixs), "Inconsistent args"

    no_arguments: DynArray[bool, MAX_POOLS] = empty(DynArray[bool, MAX_POOLS])
    for i: uint256 in range(POOL_COUNT, bound=MAX_POOLS):

        # --- Find the number of coins in the pool (N) ---

        N: uint256 = 0
        for j: uint256 in range(MAX_COINS + 1):
            success: bool = False
            res: Bytes[32] = empty(Bytes[32])
            success, res = raw_call(
                _pools[i].address,
                abi_encode(j, method_id=method_id("coins(uint256)")),
                max_outsize=32, is_static_call=True, revert_on_failure=False)
            if not success:
                assert j >= 2, "Less than 2 coins"
                N = j
                break

        # --- Check coin indexes ---

        assert _borrowed_ixs[i] != _collateral_ixs[i]
        assert _borrowed_ixs[i] < N
        assert _collateral_ixs[i] < N

        # --- Check and record if pool requires coin id in argument or not ---

        if N == 2:
            success: bool = False
            res: Bytes[32] = empty(Bytes[32])
            success, res = raw_call(
                _pools[i].address,
                abi_encode(empty(uint256), method_id=method_id("price_oracle(uint256)")),
                max_outsize=32, is_static_call=True, revert_on_failure=False)
            if not success:
                no_arguments.append(True)
            else:
                no_arguments.append(False)
        else:
            no_arguments.append(False)

    NO_ARGUMENT = no_arguments
    BORROWED_IXS = _borrowed_ixs
    COLLATERAL_IXS = _collateral_ixs


@internal
@view
def _price() -> uint256:
    """
    @dev Product over pools of (p_collateral / p_borrowed). Coin index 0 is each
         pool's reference coin (price 1e18); a non-zero index is priced via the
         pool's `price_oracle`, using the no-argument form when NO_ARGUMENT is set.
    """
    _price: uint256 = 10**18
    for i: uint256 in range(POOL_COUNT, bound=MAX_POOLS):
        p_borrowed: uint256 = 10**18
        p_collateral: uint256 = 10**18

        if NO_ARGUMENT[i]:
            if BORROWED_IXS[i] > 0:
                p_borrowed = staticcall POOLS[i].price_oracle()
            else:
                p_collateral = staticcall POOLS[i].price_oracle()
        else:
            if BORROWED_IXS[i] > 0:
                p_borrowed = staticcall POOLS[i].price_oracle(unsafe_sub(BORROWED_IXS[i], 1))
            if COLLATERAL_IXS[i] > 0:
                p_collateral = staticcall POOLS[i].price_oracle(unsafe_sub(COLLATERAL_IXS[i], 1))

        _price = _price * p_collateral // p_borrowed

    return _price


@external
@view
def price() -> uint256:
    """
    @notice Collateral price denominated in the borrowed token (1e18-scaled).
    @return The chained price across all configured pools.
    """
    return self._price()


@external
def price_w() -> uint256:
    """
    @notice Stateful entrypoint mirroring `price` (as expected by controllers).
    @dev This oracle holds no state, so the returned value equals `price`.
    @return The chained price across all configured pools.
    """
    return self._price()
