#pragma version ~=0.4.3
# @license MIT
"""
@title wstETH Rate Calculator
@notice Computes per-second yield rate for wstETH on Optimism
@dev Converts wstETH exchange rate changes to yield rates for HyperbolicDynamicMP
     Uses 2-point calculation: latest rate vs rate from avg_window ago
@custom:kill There is no need to kill this contract, just kill the underlying market
"""

from curve_stablecoin.interfaces import IRateCalculator

implements: IRateCalculator


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
# If n <= days_back: rate() returns 0 (n == 0: uint256 underflow -> revert).
#   - Runtime: HyperbolicDynamicMP reads the rate via raw_call and treats a
#     revert as 0; both are floored to MIN_TARGET_RATE = ~1% APR.
#   - Deploy time: the constructor checks the history, so deployment will
#     fail if oracle data is insufficient.
#
# Threats not currently mitigated:
#   - Oracle pause: Lido can disable rate updates via Emergency Brakes
#     Committee. Paused oracle still returns stale-but-valid data, so
#     rate() will NOT revert — it will silently compute from stale rates.
#   - Proxy upgrade with storage layout change: could reset n to 0 or
#     corrupt rate history. Would cause a zero rate (floored at runtime,
#     blocks deployment).
# -----------------------------------------------------------------------


# Constants
DAY: constant(uint256) = 86400
MIN_WINDOW: constant(uint256) = DAY            # 1 day minimum
MAX_WINDOW: constant(uint256) = 30 * DAY       # 30 days maximum


# State Variables
wsteth_oracle: public(immutable(address))
avg_window: public(immutable(uint256))


@deploy
def __init__(_oracle: address, _avg_window: uint256):
    """
    @param _oracle Address of wstETH oracle on Optimism
    @param _avg_window Averaging window in seconds (1-30 days)
    """
    assert _oracle != empty(address), "Invalid oracle"
    assert _avg_window >= MIN_WINDOW, "Window too small"
    assert _avg_window <= MAX_WINDOW, "Window too large"
    assert staticcall ITokenRateOracle(_oracle).getTokenRatesLength() > _avg_window // DAY, "Not enough history"
    wsteth_oracle = _oracle
    avg_window = _avg_window


@internal
@view
def _rate() -> uint256:
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
    days_back: uint256 = avg_window // DAY
    if n <= days_back:
        return 0
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
@view
def rate() -> uint256:
    """
    @notice Computes per-second yield rate for wstETH
    @return Per-second yield rate scaled by 10^18
    """
    return self._rate()


@external
def rate_w() -> uint256:
    """
    @notice Computes per-second yield rate for wstETH
    @dev Same as rate(), for the IRateCalculator interface; writes nothing
    @return Per-second yield rate scaled by 10^18
    """
    return self._rate()
