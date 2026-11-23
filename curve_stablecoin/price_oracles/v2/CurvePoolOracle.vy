# pragma version 0.4.3
"""
@title CurvePoolOracle
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Prices one coin of a Curve pool in terms of another coin of the same
        pool, using the pool's built-in oracle. If the pool is a stablepool
        with stored_rates they are ignored, so both prices are for the
        underlying coins of such a pool.
@dev The reported price is that of the BASE coin denominated in the QUOTE coin.
     Wired into a market, BASE is the collateral and QUOTE the borrowed token.
     This oracle holds no state, so `price_w` equals `price`.
@custom:security security@curve.finance
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin import constants as c

implements: IPriceOracle


interface Pool:
    def price_oracle(i: uint256 = 0) -> uint256: view  # Universal method!


WAD: constant(uint256) = c.WAD

POOL: public(immutable(Pool))
BASE_IDX: public(immutable(uint256))
QUOTE_IDX: public(immutable(uint256))
NO_ARGUMENT: public(immutable(bool))


@deploy
def __init__(
        _pool: Pool,
        _base_idx: uint256,
        _quote_idx: uint256
    ):
    """
    @notice Configure the Curve pool to price through.
    @dev Whether the pool's `price_oracle` takes a coin-index argument is
         auto-detected and recorded in NO_ARGUMENT.
    @param _pool Curve pool holding both coins.
    @param _base_idx Coin index of the priced (base) coin.
    @param _quote_idx Coin index of the coin the price is denominated in.
    """
    assert _base_idx != _quote_idx

    # --- Check and record if pool requires coin id in argument or not ---

    success: bool = False
    res: Bytes[32] = empty(Bytes[32])
    success, res = raw_call(
        _pool.address,
        abi_encode(empty(uint256), method_id=method_id("price_oracle(uint256)")),
        max_outsize=32, is_static_call=True, revert_on_failure=False)
    # Empty returndata means the pool has no price_oracle(uint256): either it
    # reverted, or its fallback swallowed the call (e.g. old ETH pools STOP on
    # an unknown selector, returning success with no data). Both mean the pool
    # only exposes the argument-less price_oracle().
    no_argument: bool = not success or len(res) == 0
    if no_argument:
        # A no-argument price_oracle() pool is 2-coin by construction,
        # so its coin indexes must be 0 or 1.
        assert _base_idx <= 1 and _quote_idx <= 1, "Bad coin index"

    POOL = _pool
    NO_ARGUMENT = no_argument
    BASE_IDX = _base_idx
    QUOTE_IDX = _quote_idx

    # Validate the oracle
    assert self._price() > 0


@internal
@view
def _price() -> uint256:
    """
    @notice Price of the BASE coin denominated in the QUOTE coin.
    @dev p_base / p_quote. Coin index 0 is the pool's reference coin
         (price 1e18); a non-zero index is priced via the pool's `price_oracle`,
         using the no-argument form when NO_ARGUMENT is set.
    """
    p_base: uint256 = WAD
    p_quote: uint256 = WAD

    if NO_ARGUMENT:
        if BASE_IDX > 0:
            p_base = staticcall POOL.price_oracle()
        else:
            p_quote = staticcall POOL.price_oracle()
    else:
        if BASE_IDX > 0:
            p_base = staticcall POOL.price_oracle(unsafe_sub(BASE_IDX, 1))
        if QUOTE_IDX > 0:
            p_quote = staticcall POOL.price_oracle(unsafe_sub(QUOTE_IDX, 1))

    return WAD * p_base // p_quote


@external
@view
def price() -> uint256:
    """
    @notice Price of the BASE coin denominated in the QUOTE coin (1e18-scaled).
    @return The price reported by the configured pool.
    """
    return self._price()


@external
def price_w() -> uint256:
    """
    @notice Stateful entrypoint mirroring `price` (as expected by controllers).
    @dev This oracle holds no state, so the returned value equals `price`.
    @return The price reported by the configured pool.
    """
    return self._price()
