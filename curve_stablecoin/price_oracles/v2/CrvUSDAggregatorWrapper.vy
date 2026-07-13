# pragma version 0.4.3
"""
@title crvUSD Aggregator Wrapper
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Chains a base oracle with the crvUSD stable aggregator price.

        The base oracle prices collateral in crvUSD (e.g. via chained Curve
        pools). Multiplying by the aggregator's crvUSD/USD price converts the
        result into USD terms, which is what mint markets need.

        The aggregator is itself an EMA-based, manipulation-resistant price of
        crvUSD, so no additional dampening is applied here - this wrapper is a
        straight multiply, mirroring the inline behaviour of the old
        `...WAgg` oracles.
@dev Use this contract only on Ethereum Mainnet since the Aggregator address is hardcoded
@custom:security security@curve.finance
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IPriceOracle
from curve_stablecoin import constants as c

implements: IPriceOracle


WAD: constant(uint256) = c.WAD

# crvUSD stable aggregator (Ethereum Mainnet). Gives the crvUSD/USD price (1e18-scaled).
AGG: public(constant(IPriceOracle)) = IPriceOracle(0x18672b1b0c623a30089A280Ed9256379fb0E4E62)

ORACLE: public(immutable(IPriceOracle))


@deploy
def __init__(
    _oracle: IPriceOracle,
):
    """
    @notice Wrap a base crvUSD-denominated oracle with the stable aggregator.
    @param _oracle Base price oracle, reported in crvUSD (1e18-scaled).
    """
    ORACLE = _oracle


@external
@view
def price() -> uint256:
    """
    @notice Base oracle price scaled by the crvUSD stable aggregator price (1e18).
    @return The collateral price denominated in USD.
    """
    p1: uint256 = staticcall ORACLE.price()
    return p1 * staticcall AGG.price() // WAD


@external
def price_w() -> uint256:
    """
    @notice Same as `price`, but persists the aggregator (and base oracle) state.
    @return The collateral price denominated in USD.
    """
    p1: uint256 = extcall ORACLE.price_w()
    return p1 * extcall AGG.price_w() // WAD
