# @version 0.3.10
"""
@title CryptoFromPoolVault-noncurve
@notice Price oracle for pools which contain cryptos and crvUSD. This is NOT suitable for minted crvUSD - only for lent out
        In addition to "normal" logic, multiplies by vault token's pricePerShare()
@author Curve.Fi
@license MIT
"""
interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def coins(i: uint256) -> address: view

interface Vault:
    def convertToAssets(assets: uint256) -> uint256: view


POOL: public(immutable(Pool))
BORROWED_IX: public(immutable(uint256))
COLLATERAL_IX: public(immutable(uint256))
N_COINS: public(immutable(uint256))
VAULT: public(immutable(Vault))
NO_ARGUMENT: public(immutable(bool))

RATE_MAX_SPEED: constant(uint256) = 10**16 / 60  # Max speed of Rate change

cached_timestamp: public(uint256)
cached_rate: public(uint256)


@external
def __init__(
        pool: Pool,
        N: uint256,
        borrowed_ix: uint256,
        collateral_ix: uint256,
        vault: Vault
    ):
    assert borrowed_ix != collateral_ix
    assert borrowed_ix < N
    assert collateral_ix < N

    POOL = pool
    N_COINS = N
    BORROWED_IX = borrowed_ix
    COLLATERAL_IX = collateral_ix
    VAULT = vault

    no_argument: bool = False
    if N == 2:
        success: bool = False
        res: Bytes[32] = empty(Bytes[32])
        success, res = raw_call(
            pool.address,
            _abi_encode(empty(uint256), method_id=method_id("price_oracle(uint256)")),
            max_outsize=32, is_static_call=True, revert_on_failure=False)
        if not success:
            no_argument = True
    NO_ARGUMENT = no_argument


@internal
@view
def _rate() -> uint256:
    rate: uint256 = VAULT.convertToAssets(10**18)
    cached_rate: uint256 = self.cached_rate

    if cached_rate == 0:
        return rate

    if rate > cached_rate:
        return min(rate, cached_rate * (10**18 + RATE_MAX_SPEED * (block.timestamp - self.cached_timestamp)) / 10**18)

    else:
        return max(rate, cached_rate * (10**18 - RATE_MAX_SPEED * (block.timestamp - self.cached_timestamp)) / 10**18)


@internal
def _rate_w() -> uint256:
    rate: uint256 = self._rate()
    self.cached_rate = rate
    self.cached_timestamp = block.timestamp
    return rate


@internal
@view
def _raw_price(rate: uint256) -> uint256:
    p_borrowed: uint256 = 10**18
    p_collateral: uint256 = 10**18

    if NO_ARGUMENT:
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

    return p_collateral * rate / p_borrowed


@external
@view
def price() -> uint256:
    return self._raw_price(self._rate())


@external
def price_w() -> uint256:
    return self._raw_price(self._rate_w())
