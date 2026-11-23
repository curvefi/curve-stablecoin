#pragma version 0.4.3

"""
@title syrupUSDC Rate Calculator
@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Provides a per-second yield rate for syrupUSDC, derived from the change in
        price-per-share (PPS) across up to 7 stored records spanning roughly the last week
@dev `rate_w()` is mutating: each call appends a PPS record when a day has passed (at most
     one per day) and returns the realized per-second growth over the stored window.
     `rate()` returns the same value read-only, without recording a sample.
@custom:security security@curve.finance
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IRateCalculator

implements: IRateCalculator


interface ISyrupUSDC:
    def convertToAssets(_shares: uint256) -> uint256: view


DAY: constant(uint256) = 86400
WAD: constant(uint256) = 10**18

SYRUP_USDC: public(immutable(ISyrupUSDC))


struct Record:
    pps: uint256
    ts: uint256


pps_records: public(Record[7])


@deploy
def __init__(_syrup_usdc: address):
    """
    @param _syrup_usdc Address of the syrupUSDC vault contract
    @notice Initializes the rate calculator with the syrupUSDC contract address
    """
    SYRUP_USDC = ISyrupUSDC(_syrup_usdc)


@internal
@view
def _pps() -> uint256:
    """
    @notice Current price-per-share: assets for one whole share
            (gross, doesn't take into account impairment losses)
    """
    return staticcall SYRUP_USDC.convertToAssets(WAD)


@internal
@view
def _newest() -> (uint256, uint256):
    """
    @notice Locate the newest stored record in the ring buffer
    @return (index, timestamp) of the newest record, or (0, 0) if the buffer is empty
    """
    newest_i: uint256 = 0
    newest_ts: uint256 = 0
    for i: uint256 in range(7):
        ts: uint256 = self.pps_records[i].ts
        if ts > newest_ts:
            newest_ts = ts
            newest_i = i
        else:
            break

    return newest_i, newest_ts


@internal
@view
def _rate(_newest_i: uint256, _newest_ts: uint256) -> uint256:
    """
    @notice Per-second yield rate over the stored window, treating the current PPS as a
            not-yet-recorded sample when a day is due. This is exactly what `rate_w`
            returns, computed without mutating storage.
    @return rate Yield per second, scaled by 1e18
    """

    # Empty buffer -> no rate yet.
    if _newest_ts == 0:
        return 0

    # The newest sample is the stored record, unless a day has passed since it: then
    # the current PPS would be recorded in the next slot, so use it as the (virtual)
    # newest. This mirrors the record `rate_w` would append.
    newest: Record = self.pps_records[_newest_i]
    if block.timestamp >= _newest_ts + DAY:
        _newest_i = (_newest_i + 1) % 7
        newest = Record(pps=self._pps(), ts=block.timestamp)

    # The slot right after the newest is the oldest if the buffer is full,
    # otherwise the buffer is still filling and the oldest is slot 0.
    oldest_i: uint256 = (_newest_i + 1) % 7
    if self.pps_records[oldest_i].ts == 0:
        oldest_i = 0
    oldest: Record = self.pps_records[oldest_i]

    # Single record (same slot), or no growth -> no rate.
    if newest.ts == oldest.ts or newest.pps <= oldest.pps:
        return 0

    growth: uint256 = (newest.pps - oldest.pps) * WAD // oldest.pps

    return growth // (newest.ts - oldest.ts)


@external
@view
def rate() -> uint256:
    """
    @notice Read-only per-second yield rate for syrupUSDC
    @dev Returns exactly what `rate_w` would return at the current block, but without
         recording a new PPS sample (pps_records is left unchanged). Returns 0 until at
         least two records exist, or if PPS did not grow.
    @return rate Yield per second, scaled by 1e18
    """
    newest_i: uint256 = 0
    newest_ts: uint256 = 0
    (newest_i, newest_ts) = self._newest()
    return self._rate(newest_i, newest_ts)


@external
def rate_w() -> uint256:
    """
    @notice Records the current PPS (if a day has passed since the newest record) and
            returns the realized per-second yield rate for syrupUSDC
    @dev Mutating: appends a PPS record when due, so it must be called via a normal
         (non-static) call. Records are written to a 7-slot ring buffer in sequential
         order, at least DAY apart. The rate window is therefore variable (up to ~7
         days). Returns 0 until at least two records exist, or if PPS did not grow.
    @return rate Yield per second, scaled by 1e18
    """
    newest_i: uint256 = 0
    newest_ts: uint256 = 0
    (newest_i, newest_ts) = self._newest()

    # First-ever record goes to slot 0.
    if newest_ts == 0:
        self.pps_records[0] = Record(pps=self._pps(), ts=block.timestamp)
        return 0

    # Record the current PPS in the next slot if due. It's either the oldest or empty.
    if block.timestamp >= newest_ts + DAY:
        newest_i = (newest_i + 1) % 7
        newest_ts = block.timestamp
        self.pps_records[newest_i] = Record(pps=self._pps(), ts=block.timestamp)

    # The buffer now reflects the current sample, so pass the post-write newest to
    # `_rate`: it reads the just-recorded value instead of re-adding a virtual one.
    return self._rate(newest_i, newest_ts)
