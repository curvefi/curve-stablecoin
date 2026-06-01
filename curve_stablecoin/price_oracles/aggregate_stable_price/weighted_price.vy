# pragma version 0.4.3

from snekmate.utils import math

MAX_N: constant(uint256) = 64
WAD: constant(uint256) = 10**18

SIGMA: immutable(uint256)


@deploy
def __init__(_sigma: uint256):
    """
    @notice Module constructor.
    @param _sigma Width parameter for exponential price-source penalty.
    """
    assert 10 ** 9 <= _sigma and _sigma <= WAD, "bad sigma value"
    SIGMA = _sigma


@external
@view
def sigma() -> uint256:
    """
    @notice Return the configured penalty width.
    @return WAD-scaled sigma value.
    """
    return SIGMA


@internal
@pure
def weighted_avg(
    prices: DynArray[uint256, MAX_N],
    weights: DynArray[uint256, MAX_N]
) -> uint256:
    """
    @dev Compute sum(weights[i] * prices[i]) / sum(weights[i]).
    @param prices Source prices.
    @param weights Relative WAD-scaled source weights.
    @return Weighted average price.
    """
    # sum(weights[i] * prices[i]) / sum(weights[i])
    assert len(prices) == len(weights), "length mismatch"
    weighted_sum: uint256 = 0
    weight_sum: uint256 = 0
    for i: uint256 in range(len(prices), bound=MAX_N):
        weighted_sum += weights[i] * prices[i]
        weight_sum += weights[i]
    return weighted_sum // weight_sum  # dev: zero length or zero weights


@internal
@view
def exp_penalized_price(
    prices: DynArray[uint256, MAX_N],
    weights: DynArray[uint256, MAX_N],
    p_ref: uint256
) -> uint256:
    """
    @dev Reweight sources by exponential penalty around a reference price.
    @param prices Source prices.
    @param weights Base relative WAD-scaled source weights.
    @param p_ref Reference price used to measure source deviation.
    @return Penalized weighted average price.
    """
    # Exponential penalty using squared normalized deviation:
    #   e[i] = ((p[i] - p_ref) / sigma) ** 2
    #   exp_weight[i] = weight[i] * exp(-(e[i] - min(e)))
    # Subtracting min(e) keeps the largest exponential at 1.0 and avoids
    # underweighting every source when all prices are far from p_ref.
    e: DynArray[uint256, MAX_N] = []
    e_min: uint256 = max_value(uint256)
    for i: uint256 in range(len(prices), bound=MAX_N):
        p: uint256 = prices[i]
        price_delta: uint256 = max(p, p_ref) - min(p, p_ref)
        e.append(price_delta**2 // (SIGMA**2 // WAD))
        e_min = min(e[i], e_min)

    exp_weights: DynArray[uint256, MAX_N] = []
    for i: uint256 in range(len(prices), bound=MAX_N):
        exp_weights.append(
            weights[i] * convert(
                math._wad_exp(-convert(e[i] - e_min, int256)),
                uint256
            ) // WAD
        )
    return self.weighted_avg(prices, exp_weights)
