// SPDX-License-Identifier: MIT
// Adapted from WsgemFxLlamalendOracle, Copyright (c) 2026 Arb Capital.
// https://github.com/Arb-Capital/wsgem-llamalend/blob/8596dfa09fb94a832017c65dab536a2e480dbc03/src/WsgemFxLlamalendOracle.sol
pragma solidity 0.8.25;

import {ChainlinkEMA, IChainlinkAggregator, IPriceOracle} from "./ChainlinkEMA.sol";

interface IWstGBP {
    function navprice() external view returns (uint256); // Raw NAV; zero means paused.
    function burncost() external view returns (uint256);
    function gem() external view returns (address);
    function decimals() external view returns (uint8);
}

/// @notice USD per wstGBP: capped redemption NAV times smoothed GBP/USD. crvUSD is $1.
/// @dev Hold the last price on a NAV pause or stale GBP/USD. Contract-call failures revert normally.
contract WstGBPFxOracle is IPriceOracle {
    uint256 private constant WAD = 1e18; // 18-decimal price scale: 1e18 represents one unit.
    uint256 public constant MAX_ELAPSED = 7 days; // Maximum time credited to NAV growth.
    uint256 public constant MAX_UPSIDE_SPEED = 28_935_185_185; // 0.25% per day
    uint256 public constant CHAINLINK_STALENESS_LIMIT = 30 hours; // Maximum age of the raw GBP/USD round.

    // These addresses are readable by anyone (public) and fixed at deployment (immutable).
    IWstGBP public immutable WSGEM; // wstGBP collateral wrapper.
    IChainlinkAggregator public immutable CHAINLINK_FEED; // Raw GBP/USD feed, checked for freshness.
    ChainlinkEMA public immutable CHAINLINK_ADAPTER; // Curve's stateful EMA adapter over the GBP/USD feed.

    uint256 public cachedQuote; // Saved capped NAV: tGBP per wstGBP, scaled by 1e18.
    uint256 public cachedTimestamp; // Last price_w() checkpoint time, in Unix seconds.
    uint256 public cachedPrice; // Saved USD price, including the one-wei zero-NAV floor.

    /// @notice Configure the wrapper and GBP/USD sources and initialize the price.
    constructor(IWstGBP wrapper, IChainlinkAggregator feed, ChainlinkEMA adapter) {
        WSGEM = wrapper;
        address redemptionToken = wrapper.gem();
        CHAINLINK_FEED = feed;
        CHAINLINK_ADAPTER = adapter;
        require(redemptionToken != address(0), "invalid wrapper");
        require(wrapper.decimals() == 18 && IWstGBP(redemptionToken).decimals() == 18, "invalid decimals");
        require(feed.decimals() == 8 && address(adapter.chainlinkFeed()) == address(feed), "invalid feed");
        require(adapter.OBSERVATIONS() == 20 && adapter.INTERVAL() == 30, "invalid EMA");
        (uint256 quote, bool useCachedPrice) = _getNav();
        require(!useCachedPrice && quote > 0, "unusable initial price");
        cachedQuote = quote;
        uint256 conversionRate = adapter.price();
        cachedPrice = _toUsdPrice(quote, conversionRate);
        cachedTimestamp = block.timestamp;
    }

    /// @notice Read USD per wstGBP, scaled by 1e18, without updating checkpoints.
    function price() external view returns (uint256) {
        (uint256 quote, bool useCachedPrice) = _getNav();
        if (useCachedPrice) return cachedPrice;
        if (quote == 0) return 1;
        quote = _min(quote, quoteCeiling());
        uint256 conversionRate = CHAINLINK_ADAPTER.price();
        return _toUsdPrice(quote, conversionRate);
    }

    /// @notice Return USD per wstGBP, scaled by 1e18, and save the pricing checkpoints.
    // EMA state lives in its adapter; the NAV cap and last USD price live here.
    function price_w() external returns (uint256 result) {
        (uint256 quote, bool useCachedPrice) = _getNav();
        if (useCachedPrice) {
            result = cachedPrice;
        } else if (quote == 0) {
            result = 1;
        } else {
            quote = _min(quote, quoteCeiling());
            uint256 conversionRate = CHAINLINK_ADAPTER.price_w();
            result = _toUsdPrice(quote, conversionRate);
            cachedQuote = quote;
        }
        // Each checkpoint resets the cap clock; a zero quote leaves its NAV anchor intact.
        cachedTimestamp = block.timestamp;
        cachedPrice = result;
    }

    /// @notice Whether pricing uses the cached price due to a NAV pause or stale GBP/USD.
    function frozen() external view returns (bool useCachedPrice) {
        (, useCachedPrice) = _getNav();
    }

    /// @notice Maximum NAV in GBP per wstGBP allowed by the upside cap, scaled by 1e18.
    function quoteCeiling() public view returns (uint256) {
        uint256 elapsed = _min(block.timestamp - cachedTimestamp, MAX_ELAPSED);
        return cachedQuote * (WAD + MAX_UPSIDE_SPEED * elapsed) / WAD;
    }

    // Read fee-adjusted NAV; use the cached USD price on a NAV pause or stale GBP/USD.
    function _getNav() private view returns (uint256 quote, bool useCachedPrice) {
        if (WSGEM.navprice() == 0) return (0, true);
        quote = WSGEM.burncost();
        if (quote == 0) return (0, false);
        (, int256 answer,, uint256 updatedAt,) = CHAINLINK_FEED.latestRoundData();
        require(answer > 0 && updatedAt > 0 && updatedAt <= block.timestamp, "invalid GBP/USD round");
        useCachedPrice = block.timestamp - updatedAt > CHAINLINK_STALENESS_LIMIT;
    }

    // USD per wstGBP = GBP NAV * GBP/USD; divide by WAD to keep 18 decimals.
    // Floor at one wei so the oracle never returns zero.
    function _toUsdPrice(uint256 quote, uint256 conversionRate) private pure returns (uint256) {
        uint256 result = quote * conversionRate / WAD;
        return result == 0 ? 1 : result;
    }

    function _min(uint256 a, uint256 b) private pure returns (uint256) {
        return a < b ? a : b;
    }
}
