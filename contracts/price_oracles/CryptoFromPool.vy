# @version 0.3.10
"""
@title CryptoFromPool
@notice Price oracle for pools which contain cryptos and crvUSD. This is NOT suitable for minted crvUSD - only for lent out
@author Curve.Fi
@license MIT
"""
interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!


POOL: public(immutable(Pool))
BORROWED_IX: public(immutable(uint256))
COLLATERAL_IX: public(immutable(uint256))
N_COINS: public(immutable(uint256))


@external
def __init__(
        pool: Pool,
        N: uint256,
        borrowed_ix: uint256,
        collateral_ix: uint256
    ):
    assert borrowed_ix != collateral_ix
    assert borrowed_ix < N
    assert collateral_ix < N
    POOL = pool
    N_COINS = N
    BORROWED_IX = borrowed_ix
    COLLATERAL_IX = collateral_ix


@internal
@view
def _raw_price() -> uint256:
    p_borrowed: uint256 = 10**18
    p_collateral: uint256 = 10**18

    if N_COINS == 2:
        p: uint256 = POOL.price_oracle()
        if COLLATERAL_IX > 0:
            p_collateral = p
        else:
            p_borrowed = p

    else:
        if BORROWED_IX > 0:
            p_borrowed = POOL.price_oracle(BORROWED_IX - 1)
        if COLLATERAL_IX > 0:
            p_collateral = POOL.price_oracle(COLLATERAL_IX - 1)
        

    return p_collateral * 10**18 / p_borrowed


@external
@view
def price() -> uint256:
    return self._raw_price()


@external
def price_w() -> uint256:
    return self._raw_price()
