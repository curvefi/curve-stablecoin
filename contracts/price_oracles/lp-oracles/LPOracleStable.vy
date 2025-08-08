# pragma version 0.4.3
"""
@title LPOracleStable
@author Curve.Fi
@license MIT
@notice Price oracle for Curve Stable Pool LPs. First, the oracle gets LP token price in terms of the first coin (coin0) of the pool.
        Then it chains with another oracle (target_coin/coin0) to get the final price.
"""

from contracts.interfaces import IPriceOracle
from contracts.interfaces import IStablePool
from contracts import constants as c


import lp_oracle_lib
initializes: lp_oracle_lib
exports: lp_oracle_lib.COIN0_ORACLE

MAX_COINS: constant(uint256) = 8

POOL: public(immutable(IStablePool))
NO_ARGUMENT: public(immutable(bool))
N_COINS: public(immutable(uint256))


@deploy
def __init__(_pool: IStablePool, _coin0_oracle: IPriceOracle):
    no_argument: bool = False

    # Init variables for raw calls
    res: Bytes[32] = empty(Bytes[32])
    success: bool = False

    # Find N_COINS
    for i: uint256 in range(MAX_COINS + 1):
        success, res = raw_call(
            _pool.address,
            abi_encode(i, method_id=method_id("coins(uint256)")),
            max_outsize=32, is_static_call=True, revert_on_failure=False)
        if not success:
            assert i > 1, "Less than 2 coins"
            N_COINS = i
            break

    # Check price_oracle() and record if the method requires coin id in argument or no
    for i: uint256 in range(N_COINS - 1, bound=MAX_COINS):
        success, res = raw_call(
            _pool.address,
            abi_encode(i, method_id=method_id("price_oracle(uint256)")),
            max_outsize=32, is_static_call=True, revert_on_failure=False)
        if success:
                assert convert(res, uint256) > 0, "pool.price_oracle(i) returns 0"
        else:
            assert i == 0 and N_COINS == 2, "no argument for coins > 2"
            assert staticcall _pool.price_oracle() > 0, "pool.price_oracle() returns 0"
            no_argument = True

    if _coin0_oracle.address != empty(address):
        assert staticcall _coin0_oracle.price() > 0, "coin0_oracle.price() returns 0"
        assert extcall _coin0_oracle.price_w() > 0, "coin0_oracle.price_w() returns 0"

    POOL = _pool
    NO_ARGUMENT = no_argument
    lp_oracle_lib.__init__(_coin0_oracle)


@internal
@view
def _price_in_coin0() -> uint256:
    min_p: uint256 = max_value(uint256)
    for i: uint256 in range(N_COINS, bound=MAX_COINS):
        p_oracle: uint256 = c.WAD
        if i > 0:
            if NO_ARGUMENT:
                p_oracle = staticcall POOL.price_oracle()
            else:
                p_oracle = staticcall POOL.price_oracle(unsafe_sub(i, 1))

        if p_oracle < min_p:
            min_p = p_oracle

    return min_p * (staticcall POOL.get_virtual_price()) // c.WAD


@external
@view
def price() -> uint256:
    return self._price_in_coin0() * lp_oracle_lib._coin0_oracle_price() // c.WAD


@external
def price_w() -> uint256:
    return self._price_in_coin0() * lp_oracle_lib._coin0_oracle_price_w() // c.WAD
