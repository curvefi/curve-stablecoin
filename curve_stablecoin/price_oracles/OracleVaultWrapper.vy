# @version 0.3.10
"""
@title OracleVaultWrapper
@notice Wraps an external price oracle to be vault-aware (pricePerShare) and invertible
@author Curve.Fi
@license MIT
"""

interface Oracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

interface Vault:
    def pricePerShare() -> uint256: view


ORACLE: public(immutable(Oracle))
VAULT: public(immutable(Vault))
IS_INVERTED: public(immutable(bool))

PPS_MAX_SPEED: constant(uint256) = 10**16 / 60  # Max speed of pricePerShare change
DEAD_SHARES: constant(uint256) = 1000

cached_price_per_share: public(uint256)
cached_timestamp: public(uint256)


@external
def __init__(
        oracle: Oracle,
        vault: Vault,
        is_inverted: bool
    ):
    ORACLE = oracle
    VAULT = vault
    IS_INVERTED = is_inverted
    self.cached_price_per_share = VAULT.pricePerShare()
    self.cached_timestamp = block.timestamp


@internal
@view
def _pps() -> uint256:
    pps: uint256 = VAULT.pricePerShare()
    if pps == 10**18 / DEAD_SHARES:
        return pps
    else:
        return min(pps, self.cached_price_per_share * (10**18 + PPS_MAX_SPEED * (block.timestamp - self.cached_timestamp)) / 10**18)


@internal
def _pps_w() -> uint256:
    pps: uint256 = VAULT.pricePerShare()
    if pps != 10**18 / DEAD_SHARES:
        pps = min(pps, self.cached_price_per_share * (10**18 + PPS_MAX_SPEED * (block.timestamp - self.cached_timestamp)) / 10**18)
    self.cached_price_per_share = pps
    self.cached_timestamp = block.timestamp
    return pps


@internal
@view
def _raw_price(p: uint256, pps: uint256) -> uint256:
    if IS_INVERTED:
        return pps * 10**18 / p
    else:
        return p * pps / 10**18


@external
@view
def price() -> uint256:
    return self._raw_price(ORACLE.price(), self._pps())


@external
def price_w() -> uint256:
    return self._raw_price(ORACLE.price_w(), self._pps_w())
