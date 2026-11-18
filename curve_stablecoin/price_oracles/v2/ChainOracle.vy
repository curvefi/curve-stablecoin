# pragma version 0.4.3
"""
@title ChainOracle
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Chains price oracles into a single price by multiplying them. Each
        oracle must be quoted in the base coin of the next one, so chaining an
        A/B oracle with a B/C oracle reports the price of A in C.
@dev This contract holds no state of its own, but the chained oracles may:
     `price` reads them all through `price`, while `price_w` goes through
     `price_w` so that any state they keep is persisted.
@custom:security security@curve.finance
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin import constants as c

implements: IPriceOracle


WAD: constant(uint256) = c.WAD
MAX_ORACLES: constant(uint256) = 10

ORACLES: public(immutable(DynArray[IPriceOracle, MAX_ORACLES]))
ORACLE_COUNT: public(immutable(uint256))


@deploy
def __init__(_oracles: DynArray[IPriceOracle, MAX_ORACLES]):
    """
    @notice Configure the chain of oracles to price through.
    @param _oracles Price oracles to chain, in order (1 to MAX_ORACLES).
    """
    ORACLES = _oracles
    ORACLE_COUNT = len(_oracles)
    assert ORACLE_COUNT > 0, "No oracles"

    # Validate the oracle
    assert self._price() > 0
    assert self._price_w() > 0


@internal
@view
def _price() -> uint256:
    """
    @notice Price of the first oracle's base coin in the last oracle's quote coin.
    @dev Product of the chained prices, rescaled to 1e18 at every step.
    """
    chained: uint256 = WAD
    for i: uint256 in range(ORACLE_COUNT, bound=MAX_ORACLES):
        p: uint256 = staticcall ORACLES[i].price()
        chained = chained * p // WAD

    return chained


@external
@view
def price() -> uint256:
    """
    @notice Price of the first oracle's base coin in the last oracle's quote
            coin (1e18-scaled).
    @return The chained price across all configured oracles.
    """
    return self._price()


@internal
def _price_w() -> uint256:
    """
    @notice Same as `_price`, but persisting the state of every chained oracle.
    @dev Cannot reuse the read-only path: the chained oracles are the ones
         holding state, so each has to be reached through its own `price_w`.
    """
    chained: uint256 = WAD
    for i: uint256 in range(ORACLE_COUNT, bound=MAX_ORACLES):
        p: uint256 = extcall ORACLES[i].price_w()
        chained = chained * p // WAD

    return chained


@external
def price_w() -> uint256:
    """
    @notice Same as `price`, but persists the state of every chained oracle.
    @return The chained price across all configured oracles.
    """
    return self._price_w()
