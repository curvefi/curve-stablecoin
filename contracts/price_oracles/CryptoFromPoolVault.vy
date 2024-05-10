# @version 0.3.10
"""
@title CryptoFromPoolVault
@notice Price oracle for pools which contain cryptos and crvUSD. This is NOT suitable for minted crvUSD - only for lent out
        In addition to "normal" logic, multiplies by vault token's pricePerShare()
@author Curve.Fi
@license MIT
"""
interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def coins(i: uint256) -> address: view

interface Vault:
    def pricePerShare() -> uint256: view
    def borrowed_token() -> address: view


POOL: public(immutable(Pool))
BORROWED_IX: public(immutable(uint256))
COLLATERAL_IX: public(immutable(uint256))
N_COINS: public(immutable(uint256))
VAULT: public(immutable(Vault))
NO_ARGUMENT: public(immutable(bool))

PPS_MAX_SPEED: constant(uint256) = 10**16 / 60  # Max speed of pricePerShare change

cached_price_per_share: public(uint256)
cached_timestamp: public(uint256)


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

    self.cached_price_per_share = VAULT.pricePerShare()
    self.cached_timestamp = block.timestamp


@internal
@view
def _pps() -> uint256:
    return min(VAULT.pricePerShare(), self.cached_price_per_share * (10**18 + PPS_MAX_SPEED * (block.timestamp - self.cached_timestamp)) / 10**18)


@internal
def _pps_w() -> uint256:
    pps: uint256 = min(VAULT.pricePerShare(), self.cached_price_per_share * (10**18 + PPS_MAX_SPEED * (block.timestamp - self.cached_timestamp)) / 10**18)
    self.cached_price_per_share = pps
    self.cached_timestamp = block.timestamp
    return pps


@internal
@view
def _raw_price(pps: uint256) -> uint256:
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

    return p_collateral * pps / p_borrowed


@external
@view
def price() -> uint256:
    return self._raw_price(self._pps())


@external
def price_w() -> uint256:
    return self._raw_price(self._pps_w())
