# @version 0.3.10
"""
@title USD0LpOracle
@notice Price oracle for pools USD0/USD0+ LP token. It uses USD0/crvUSD price oracle and aggregator price
@author Curve.Fi
@license MIT
"""
interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!
    def get_virtual_price() -> uint256: view
    def coins(i: uint256) -> address: view

interface StableAggregator:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable
    def stablecoin() -> address: view


LP_POOL: public(immutable(Pool))
POOL: public(immutable(Pool))
BORROWED_IX: public(immutable(uint256))
COLLATERAL_IX: public(immutable(uint256))
COLLATERAL_IX_IN_LP: public(immutable(uint256))
N_COINS: public(immutable(uint256))
NO_ARGUMENT: public(immutable(bool))
AGG: public(immutable(StableAggregator))

PPS_MAX_SPEED: constant(uint256) = 10**16 / 60  # Max speed of pricePerShare change

cached_price_per_share: public(uint256)
cached_timestamp: public(uint256)


@external
def __init__(
        lp_pool: Pool,
        pool: Pool,
        N: uint256,
        borrowed_ix: uint256,
        collateral_ix: uint256,
        agg: StableAggregator
    ):
    assert borrowed_ix != collateral_ix
    assert borrowed_ix < N
    assert collateral_ix < N

    LP_POOL = lp_pool
    POOL = pool
    N_COINS = N
    BORROWED_IX = borrowed_ix
    COLLATERAL_IX = collateral_ix
    AGG = agg

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

    collateral_ix_in_lp: uint256 = 1000
    collateral_coin: address = pool.coins(collateral_ix)
    for i in range(2):
        if lp_pool.coins(i) == collateral_coin:
            collateral_ix_in_lp = i
    assert collateral_ix_in_lp != 1000
    COLLATERAL_IX_IN_LP = collateral_ix_in_lp

    self.cached_price_per_share = lp_pool.get_virtual_price()
    self.cached_timestamp = block.timestamp


@internal
@view
def _pps() -> uint256:
    return min(LP_POOL.get_virtual_price(), self.cached_price_per_share * (10**18 + PPS_MAX_SPEED * (block.timestamp - self.cached_timestamp)) / 10**18)


@internal
def _pps_w() -> uint256:
    pps: uint256 = min(LP_POOL.get_virtual_price(), self.cached_price_per_share * (10**18 + PPS_MAX_SPEED * (block.timestamp - self.cached_timestamp)) / 10**18)
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

    lp_coin_oracle: uint256 = LP_POOL.price_oracle(0)  # For 2 coins
    if COLLATERAL_IX_IN_LP > 0:
        lp_coin_oracle = 10**36 / lp_coin_oracle
    p_lp: uint256 = pps * min(10**18, lp_coin_oracle) / 10**18

    return p_collateral * p_lp / p_borrowed


@external
@view
def price() -> uint256:
    return self._raw_price(self._pps()) * AGG.price() / 10**18


@external
def price_w() -> uint256:
    return self._raw_price(self._pps_w()) * AGG.price_w() / 10**18
