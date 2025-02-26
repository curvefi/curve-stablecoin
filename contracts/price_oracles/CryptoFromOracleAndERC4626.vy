# @version 0.3.10
"""
@title CryptoFromOracleAndERC4626
@author Curve.Fi
@license MIT
"""
interface Oracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


interface ERC4626:
    def convertToAssets(shares: uint256) -> uint256: view


ORACLE: public(immutable(Oracle))
VAULT: public(immutable(ERC4626))


@external
def __init__(
        oracle: Oracle,
        vault: ERC4626
    ):
    ORACLE = oracle
    VAULT = vault


@external
@view
def price() -> uint256:
    p1: uint256 = ORACLE.price()
    p2: uint256 = VAULT.convertToAssets(10**18)
    return p1 * p2 / 10**18


@external
def price_w() -> uint256:
    p1: uint256 = ORACLE.price_w()
    p2: uint256 = VAULT.convertToAssets(10**18)
    return p1 * p2 / 10**18
