# pragma version 0.4.3
# SPDX-License-Identifier: MIT
"""
@title Chainlink EMA
@license MIT
@notice Samples Chainlink rounds at fixed intervals; does not enforce freshness.
@dev Port of ChainlinkEMA.sol (https://github.com/defidotmoney/dfm-contracts).
     History walks revert on exhaustion. The caller handles stale feeds and failed reads.
"""

from curve_stablecoin.interfaces import IPriceOracle

implements: IPriceOracle


interface Feed:
    def decimals() -> uint8: view
    def latestRoundData() -> (uint80, int256, uint256, uint256, uint80): view
    def getRoundData(round_id: uint80) -> (uint80, int256, uint256, uint256, uint80): view


struct Response:
    roundId: uint80
    updatedAt: uint256
    decimals: uint8
    answer: uint256


WAD: constant(uint256) = 10**18
MAX_SAMPLES: constant(uint256) = 256
MAX_ROUNDS: constant(uint256) = 1024

chainlinkFeed: public(immutable(Feed))
OBSERVATIONS: public(immutable(uint256))
INTERVAL: public(immutable(uint256))
SMOOTHING_FACTOR: public(immutable(uint256))
MAX_LOOKBACK: immutable(uint256)
storedPrice: public(uint256)
storedObservationTimestamp: public(uint256)
storedResponse: public(Response)


@deploy
def __init__(feed: Feed, observations: uint256, interval: uint256):
    assert feed.address != empty(address) and interval > 0
    assert 0 < observations and observations <= MAX_SAMPLES // 2
    chainlinkFeed = feed
    OBSERVATIONS = observations
    INTERVAL = interval
    SMOOTHING_FACTOR = 2 * WAD // (observations + 1)
    MAX_LOOKBACK = observations * 2
    self.storedPrice, self.storedResponse = self._calculate()
    self.storedObservationTimestamp = self._observation()


@internal
@view
def _observation() -> uint256:
    return block.timestamp // INTERVAL * INTERVAL


@internal
@pure
def _response(round_id: uint80, answer: int256, updated_at: uint256, decimals: uint8) -> Response:
    assert answer > 0, "DFM: Chainlink answer too low"
    return Response(
        roundId=round_id,
        updatedAt=updated_at,
        decimals=decimals,
        answer=convert(answer, uint256) * 10**(18 - convert(decimals, uint256)),
    )


@internal
@view
def _calculate() -> (uint256, Response):
    observation: uint256 = self._observation()
    initialized: bool = self.storedPrice != 0
    if initialized and observation == self.storedObservationTimestamp:
        return self.storedPrice, self.storedResponse

    round_id: uint80 = 0
    answer: int256 = 0
    updated_at: uint256 = 0
    ignored_start: uint256 = 0
    ignored_round: uint80 = 0
    (
        round_id, answer, ignored_start, updated_at, ignored_round
    ) = staticcall chainlinkFeed.latestRoundData()
    decimals: uint8 = self.storedResponse.decimals
    same_phase: bool = (
        initialized
        and convert(round_id, uint256) >> 64 == convert(self.storedResponse.roundId, uint256) >> 64
    )
    if not same_phase:
        decimals = staticcall chainlinkFeed.decimals()
        assert decimals <= 18, "DFM: Chainlink decimals too high"
    latest: Response = self._response(round_id, answer, updated_at, decimals)
    response: Response = latest

    # Short gaps extend the stored EMA; idle periods and phase changes reseed it.
    incremental: bool = (
        same_phase and observation < self.storedObservationTimestamp + MAX_LOOKBACK * INTERVAL
    )
    count: uint256 = MAX_LOOKBACK
    stop: uint80 = convert((convert(round_id, uint256) >> 64) << 64 | 1, uint80)
    if incremental:
        count = (observation - self.storedObservationTimestamp) // INTERVAL
        stop = self.storedResponse.roundId

    samples: DynArray[uint256, MAX_SAMPLES] = []
    reads: uint256 = 0
    for _: uint256 in range(count, bound=MAX_SAMPLES):
        # The answer at an observation is the last round strictly before it.
        for __: uint256 in range(MAX_ROUNDS):
            if response.updatedAt < observation or response.roundId == stop:
                break
            assert reads < MAX_ROUNDS, "round history too long"
            (
                round_id, answer, ignored_start, updated_at, ignored_round
            ) = staticcall chainlinkFeed.getRoundData(response.roundId - 1)
            response = self._response(round_id, answer, updated_at, decimals)
            reads += 1
        assert (
            response.updatedAt < observation or response.roundId == stop
        ), "round history too long"
        if not incremental and response.updatedAt >= observation:
            break
        samples.append(response.answer)
        if len(samples) < count:
            observation -= INTERVAL
    price: uint256 = self.storedPrice
    if not incremental:
        if len(samples) == 0:
            return response.answer, latest
        price = samples.pop()
    for i: uint256 in range(len(samples), bound=MAX_SAMPLES):
        price = (
            samples[len(samples) - 1 - i] * SMOOTHING_FACTOR + price * (WAD - SMOOTHING_FACTOR)
        ) // WAD
    return price, latest


@external
@view
def price() -> uint256:
    return self._calculate()[0]


@external
def price_w() -> uint256:
    self.storedPrice, self.storedResponse = self._calculate()
    self.storedObservationTimestamp = self._observation()
    return self.storedPrice
