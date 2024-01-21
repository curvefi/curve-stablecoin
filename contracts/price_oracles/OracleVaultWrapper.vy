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
    def borrowed_token() -> address: view
    def collateral_token() -> address: view


ORACLE: public(immutable(Oracle))
VAULT: public(immutable(Vault))
IS_INVERTED: public(immutable(bool))


@external
def __init__(
        oracle: Oracle,
        vault: Vault,
        is_inverted: bool
    ):
    ORACLE = oracle
    VAULT = vault
    IS_INVERTED = is_inverted


@internal
@view
def _raw_price(p: uint256) -> uint256:
    if IS_INVERTED:
        return VAULT.pricePerShare() * 10**18 / p
    else:
        return p * VAULT.pricePerShare() / 10**18


@external
@view
def price() -> uint256:
    return self._raw_price(ORACLE.price())


@external
def price_w() -> uint256:
    return self._raw_price(ORACLE.price_w())
