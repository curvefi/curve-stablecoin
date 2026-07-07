#pragma version 0.4.3
"""
@title OracleFromCurvePools
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice The oracle chains multiple Curve pools oracles. If there are stablepools with stored_rates in the chain - they are ignored,
        and all the prices in the chain are for underlying coins of such pools.
"""

MAX_COINS: constant(uint256) = 8
MAX_POOLS: constant(uint256) = 8


interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def coins(i: uint256) -> address: view


POOLS: public(immutable(DynArray[Pool, MAX_POOLS]))
BORROWED_IX: public(immutable(DynArray[uint256, MAX_POOLS]))
COLLATERAL_IX: public(immutable(DynArray[uint256, MAX_POOLS]))
NO_ARGUMENT: public(immutable(DynArray[bool, MAX_POOLS]))
POOL_COUNT: public(immutable(uint256))


@deploy
def __init__(
        pools: DynArray[Pool, MAX_POOLS],
        borrowed_ixs: DynArray[uint256, MAX_POOLS],
        collateral_ixs: DynArray[uint256, MAX_POOLS]
    ):
    POOLS = pools
    POOL_COUNT = len(pools)
    assert POOL_COUNT > 0, "No pools"
    assert POOL_COUNT == len(borrowed_ixs) and POOL_COUNT == len(collateral_ixs), "Inconsistent args"

    no_arguments: DynArray[bool, MAX_POOLS] = empty(DynArray[bool, MAX_POOLS])
    for i: uint256 in range(POOL_COUNT, bound=MAX_POOLS):

        # --- Find the number of coins in the pool (N) ---

        N: uint256 = 0
        for j: uint256 in range(MAX_COINS + 1):
            success: bool = False
            res: Bytes[32] = empty(Bytes[32])
            success, res = raw_call(
                pools[i].address,
                abi_encode(j, method_id=method_id("coins(uint256)")),
                max_outsize=32, is_static_call=True, revert_on_failure=False)
            if not success:
                assert j >= 2, "Less than 2 coins"
                N = j
                break

        # --- Check coin indexes ---

        assert borrowed_ixs[i] != collateral_ixs[i]
        assert borrowed_ixs[i] < N
        assert collateral_ixs[i] < N

        # --- Check and record if pool requires coin id in argument or not ---

        if N == 2:
            success: bool = False
            res: Bytes[32] = empty(Bytes[32])
            success, res = raw_call(
                pools[i].address,
                abi_encode(empty(uint256), method_id=method_id("price_oracle(uint256)")),
                max_outsize=32, is_static_call=True, revert_on_failure=False)
            if not success:
                no_arguments.append(True)
            else:
                no_arguments.append(False)
        else:
            no_arguments.append(False)

    NO_ARGUMENT = no_arguments
    BORROWED_IX = borrowed_ixs
    COLLATERAL_IX = collateral_ixs


@internal
@view
def _price() -> uint256:
    _price: uint256 = 10**18
    for i: uint256 in range(POOL_COUNT, bound=MAX_POOLS):
        p_borrowed: uint256 = 10**18
        p_collateral: uint256 = 10**18

        if NO_ARGUMENT[i]:
            if BORROWED_IX[i] > 0:
                p_borrowed = staticcall POOLS[i].price_oracle()
            else:
                p_collateral = staticcall POOLS[i].price_oracle()
        else:
            if BORROWED_IX[i] > 0:
                p_borrowed = staticcall POOLS[i].price_oracle(unsafe_sub(BORROWED_IX[i], 1))
            if COLLATERAL_IX[i] > 0:
                p_collateral = staticcall POOLS[i].price_oracle(unsafe_sub(COLLATERAL_IX[i], 1))

        _price = _price * p_collateral // p_borrowed

    return _price


@external
@view
def price() -> uint256:
    return self._price()


@external
def price_w() -> uint256:
    return self._price()
