# pragma version 0.4.3
"""
@title LPOracleCrypto
@author Curve.Fi
@license MIT
@notice Price oracle for Curve Crypto Pool LPs. First, the oracle gets LP token price in terms of the first coin (coin0) of the pool.
        Then it chains with another oracle (target_coin/coin0) to get the final price.
"""
from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin.interfaces import ICryptoPool
from contracts import constants as c


import lp_oracle_lib
initializes: lp_oracle_lib
exports: lp_oracle_lib.COIN0_ORACLE


POOL: public(immutable(ICryptoPool))


@deploy
def __init__(_pool: ICryptoPool, _coin0_oracle: IPriceOracle):
    assert staticcall _pool.lp_price() > 0, "pool.lp_price() returns 0"
    if _coin0_oracle.address != empty(address):
        assert staticcall _coin0_oracle.price() > 0, "coin0_oracle.price() returns 0"
        assert extcall _coin0_oracle.price_w() > 0, "coin0_oracle.price_w() returns 0"
    POOL = _pool
    lp_oracle_lib.__init__(_coin0_oracle)


@internal
@view
def _price_in_coin0() -> uint256:
    return staticcall POOL.lp_price()


@external
@view
def price() -> uint256:
    return self._price_in_coin0() * lp_oracle_lib._coin0_oracle_price() // c.WAD


@external
def price_w() -> uint256:
    return self._price_in_coin0() * lp_oracle_lib._coin0_oracle_price_w() // c.WAD
