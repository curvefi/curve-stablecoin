# @version 0.4.1
#pragma optimize gas
#pragma evm-version shanghai

"""
@title LPOracleCrypto
@author Curve.Fi
@license GNU Affero General Public License v3.0 only
@notice Price oracle for Curve Crypto Pool LPs. First, the oracle gets LP token price in terms of the first coin (coin0) of the pool.
        Then it chains with another oracle (target_coin/coin0) to get the final price.
"""

import lp_oracle_lib
initializes: lp_oracle_lib
exports: lp_oracle_lib.COIN0_ORACLE


interface CryptoPool:
    def lp_price() -> uint256: view  # Exists only for cryptopools


POOL: public(immutable(CryptoPool))

@deploy
def __init__(pool: CryptoPool, coin0_oracle: lp_oracle_lib.PriceOracle):
    assert staticcall pool.lp_price() > 0
    if coin0_oracle.address != empty(address):
        assert staticcall coin0_oracle.price() > 0
        assert extcall coin0_oracle.price_w() > 0
    POOL = pool
    lp_oracle_lib.__init__(coin0_oracle)


@internal
@view
def _price_in_coin0() -> uint256:
    return staticcall POOL.lp_price()


@external
@view
def price() -> uint256:
    return self._price_in_coin0() * lp_oracle_lib._coin0_oracle_price() // 10 ** 18


@external
def price_w() -> uint256:
    return self._price_in_coin0() * lp_oracle_lib._coin0_oracle_price_w() // 10 ** 18
