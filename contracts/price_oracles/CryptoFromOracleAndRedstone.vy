# @version 0.3.10
"""
@title CryptoFromOracleAndRedstone
@author Curve.Fi
@license MIT
"""
interface Oracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


interface Redstone:
    def latestAnswer() -> uint256: view


ORACLE: public(immutable(Oracle))
REDSTONE: public(immutable(Redstone))


@external
def __init__(
        oracle: Oracle,
        redstone: Redstone
    ):
    ORACLE = oracle
    REDSTONE = redstone


@external
@view
def price() -> uint256:
    p1: uint256 = ORACLE.price()
    p2: uint256 = REDSTONE.latestAnswer()
    assert p2 > 0
    return p1 * p2 / 10**18


@external
def price_w() -> uint256:
    p1: uint256 = ORACLE.price_w()
    p2: uint256 = REDSTONE.latestAnswer()
    assert p2 > 0
    return p1 * p2 / 10**18
