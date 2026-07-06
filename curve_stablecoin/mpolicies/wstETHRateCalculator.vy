#pragma version ~=0.4.3
# @license MIT
"""
@title wstETH Rate Calculator
@notice Computes per-second yield rate for wstETH on Optimism
@dev Converts wstETH exchange rate changes to yield rates for EMAMonetaryPolicy
     Uses 2-point calculation: latest rate vs rate from avg_window ago
"""

from snekmate.auth import ownable
from snekmate.auth import ownable_2step

initializes: ownable
initializes: ownable_2step[ownable := ownable]

exports: (
    ownable_2step.owner,
    ownable_2step.pending_owner,
    ownable_2step.transfer_ownership,
    ownable_2step.accept_ownership,
)


interface ITokenRateOracle:
    def getTokenRateByIndex(tokenRateIndex_: uint256) -> (uint256, uint256, uint256): view
    def getTokenRatesLength() -> uint256: view


# -----------------------------------------------------------------------
# Risk Assumptions & Oracle Dependency
# -----------------------------------------------------------------------
# This contract assumes the Lido TokenRateOracle on Optimism has sufficient
# history (n >= days_back + 1 entries). The oracle is an OssifiableProxy
# (upgradeable by Lido DAO) with 400+ daily entries at time of writing.
#
# If n < 2 or n <= days_back: uint256 underflow -> revert.
#   - Runtime: EMAMonetaryPolicy.ema_rate_w() catches reverts via raw_call
#     and falls back to prev_ma_rate (floored to MIN_EMA_RATE = ~1% APR).
#   - Deploy time: EMAMonetaryPolicy constructor calls rate() directly
#     (no raw_call), so deployment will fail if oracle data is insufficient.
#
# Threats not currently mitigated:
#   - Oracle pause: Lido can disable rate updates via Emergency Brakes
#     Committee. Paused oracle still returns stale-but-valid data, so
#     rate() will NOT revert — it will silently compute from stale rates.
#   - Proxy upgrade with storage layout change: could reset n to 0 or
#     corrupt rate history. Would cause revert (caught at runtime, blocks
#     deployment).
# -----------------------------------------------------------------------


# Constants
MIN_WINDOW: constant(uint256) = 86400          # 1 day minimum
MAX_WINDOW: constant(uint256) = 30 * 86400     # 30 days maximum


# Events
event AvgWindowUpdated:
    old_window: uint256
    new_window: uint256


# State Variables
wsteth_oracle: public(immutable(address))
avg_window: public(uint256)


@deploy
def __init__(_oracle: address, _owner: address, _avg_window: uint256):
    """
    @param _oracle Address of wstETH oracle on Optimism
    @param _owner Admin address for configuration
    @param _avg_window Averaging window in seconds (1-30 days)
    """
    assert _oracle != empty(address), "Invalid oracle"
    assert _owner != empty(address), "Invalid owner"
    assert _avg_window >= MIN_WINDOW, "Window too small"
    assert _avg_window <= MAX_WINDOW, "Window too large"
    wsteth_oracle = _oracle
    ownable.__init__()
    ownable_2step.__init__()
    if _owner != msg.sender:
        ownable_2step._transfer_ownership(_owner)
    self.avg_window = _avg_window


@external
@view
def rate() -> uint256:
    """
    @notice Computes per-second yield rate for wstETH
    @return Per-second yield rate scaled by 10^18
    @dev Calculates yield from exchange rate change over avg_window
         Uses 2-point calculation: latest rate vs rate from ~avg_window ago
    """
    oracle: ITokenRateOracle = ITokenRateOracle(wsteth_oracle)
    n: uint256 = staticcall oracle.getTokenRatesLength()

    # Get latest rate
    r_latest: uint256 = 0
    ts_latest: uint256 = 0
    rateReceivedL2Timestamp_unused: uint256 = 0
    r_latest, ts_latest, rateReceivedL2Timestamp_unused = staticcall oracle.getTokenRateByIndex(n - 1)

    # Calculate index for ~avg_window ago (assumes ~daily oracle updates)
    days_back: uint256 = self.avg_window // 86400
    oldest_idx: uint256 = n - 1 - days_back

    # Get oldest rate
    r_oldest: uint256 = 0
    ts_oldest: uint256 = 0
    r_oldest, ts_oldest, rateReceivedL2Timestamp_unused = staticcall oracle.getTokenRateByIndex(oldest_idx)

    # Compute per-second yield using actual timestamp delta
    if ts_latest <= ts_oldest:
        return 0

    if r_latest <= r_oldest:
        return 0

    time_delta: uint256 = ts_latest - ts_oldest
    rate_delta: uint256 = r_latest - r_oldest

    return rate_delta * 10**18 // r_oldest // time_delta


@external
def set_avg_window(new_window: uint256):
    """
    @notice Update averaging window
    @param new_window New window in seconds (1-30 days)
    """
    ownable._check_owner()
    assert new_window >= MIN_WINDOW, "Window too small"
    assert new_window <= MAX_WINDOW, "Window too large"

    old_window: uint256 = self.avg_window
    self.avg_window = new_window

    log AvgWindowUpdated(old_window=old_window, new_window=new_window)
