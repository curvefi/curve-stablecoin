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


interface CryptoPool:
    def lp_price() -> uint256: view  # Exists only for cryptopools

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


POOL: public(immutable(CryptoPool))
COIN0_ORACLE: public(immutable(PriceOracle))


@deploy
def __init__(pool: CryptoPool, coin0_oracle: PriceOracle):
    assert staticcall pool.lp_price() > 0
    if coin0_oracle.address != empty(address):
        assert staticcall coin0_oracle.price() > 0
        assert extcall coin0_oracle.price_w() > 0
    POOL = pool
    COIN0_ORACLE = coin0_oracle


@internal
@view
def _coin0_oracle_price() -> uint256:
    if COIN0_ORACLE.address != empty(address):
        return staticcall COIN0_ORACLE.price()
    else:
        return 10**18


@internal
def _coin0_oracle_price_w() -> uint256:
    if COIN0_ORACLE.address != empty(address):
        return extcall COIN0_ORACLE.price_w()
    else:
        return 10**18


@internal
@view
def _price_in_coin0() -> uint256:
    return staticcall POOL.lp_price()


@external
@view
def price() -> uint256:
    return self._price_in_coin0() * self._coin0_oracle_price() // 10 ** 18


@external
def price_w() -> uint256:
    return self._price_in_coin0() * self._coin0_oracle_price_w() // 10 ** 18
