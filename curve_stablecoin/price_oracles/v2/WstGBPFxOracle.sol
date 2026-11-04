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
    uint256 public constant CHAINLINK_GBP_USD_STALENESS_LIMIT = 30 hours; // Maximum age of the raw GBP/USD round.

    // These addresses are readable by anyone (public) and fixed at deployment (immutable).
    IWstGBP public immutable WSGEM; // wstGBP collateral wrapper.
    IChainlinkAggregator public immutable CHAINLINK_GBP_USD_FEED; // Raw GBP/USD feed, checked for freshness.
    ChainlinkEMA public immutable CHAINLINK_GBP_USD_EMA; // Smoothed GBP/USD price used for conversion to USD.

    uint256 public cachedQuote; // Saved capped NAV: tGBP per wstGBP, scaled by 1e18.
    uint256 public cachedTimestamp; // Last price_w() checkpoint time, in Unix seconds.
    uint256 public cachedPrice; // Saved USD price, including the one-wei zero-NAV floor.

    /// @notice Configure the wrapper and GBP/USD sources and initialize the price.
    constructor(IWstGBP wrapper, IChainlinkAggregator feed, ChainlinkEMA ema) {
        WSGEM = wrapper;
        address redemptionToken = wrapper.gem();
        CHAINLINK_GBP_USD_FEED = feed;
        CHAINLINK_GBP_USD_EMA = ema;
        require(redemptionToken != address(0), "invalid wrapper");
        require(wrapper.decimals() == 18 && IWstGBP(redemptionToken).decimals() == 18, "invalid decimals");
        require(feed.decimals() == 8 && address(ema.chainlinkFeed()) == address(feed), "invalid feed");
        require(ema.OBSERVATIONS() == 20 && ema.INTERVAL() == 30, "invalid EMA");
        (uint256 quote, bool useCachedPrice) = _quote();
        require(!useCachedPrice && quote > 0, "unusable initial price");
        cachedQuote = quote;
        cachedPrice = _compose(quote, ema.price());
        cachedTimestamp = block.timestamp;
    }

    /// @notice Read USD per wstGBP, scaled by 1e18, without updating checkpoints.
    function price() external view returns (uint256) {
        (uint256 quote, bool useCachedPrice) = _quote();
        if (useCachedPrice) return cachedPrice;
        return quote == 0 ? 1 : _compose(_min(quote, quoteCeiling()), CHAINLINK_GBP_USD_EMA.price());
    }

    /// @notice Return USD per wstGBP, scaled by 1e18, and save the pricing checkpoints.
    function price_w() external returns (uint256 result) {
        (uint256 quote, bool useCachedPrice) = _quote();
        if (useCachedPrice) {
            result = cachedPrice;
        } else if (quote == 0) {
            result = 1;
        } else {
            quote = _min(quote, quoteCeiling());
            result = _compose(quote, CHAINLINK_GBP_USD_EMA.price_w());
            cachedQuote = quote;
        }
        // Each checkpoint resets the cap clock; a zero quote leaves its NAV anchor intact.
        cachedTimestamp = block.timestamp;
        cachedPrice = result;
    }

    /// @notice Whether pricing uses the cached price due to a NAV pause or stale GBP/USD.
    function frozen() external view returns (bool useCachedPrice) {
        (, useCachedPrice) = _quote();
    }

    /// @notice Maximum NAV in GBP per wstGBP allowed by the upside cap, scaled by 1e18.
    function quoteCeiling() public view returns (uint256) {
        uint256 elapsed = _min(block.timestamp - cachedTimestamp, MAX_ELAPSED);
        return cachedQuote * (WAD + MAX_UPSIDE_SPEED * elapsed) / WAD;
    }

    // Read redemption NAV and check for a NAV pause or stale GBP/USD.
    function _quote() private view returns (uint256 quote, bool useCachedPrice) {
        if (WSGEM.navprice() == 0) return (0, true);
        quote = WSGEM.burncost();
        if (quote == 0) return (0, false);
        (, int256 answer,, uint256 updatedAt,) = CHAINLINK_GBP_USD_FEED.latestRoundData();
        require(answer > 0 && updatedAt > 0 && updatedAt <= block.timestamp, "invalid GBP/USD round");
        useCachedPrice = block.timestamp - updatedAt > CHAINLINK_GBP_USD_STALENESS_LIMIT;
    }

    // USD per wstGBP = GBP NAV * GBP/USD; divide by WAD to keep 18 decimals.
    // Floor at one wei so the oracle never returns zero.
    function _compose(uint256 quote, uint256 gbpUsdPrice) private pure returns (uint256) {
        uint256 result = quote * gbpUsdPrice / WAD;
        return result == 0 ? 1 : result;
    }

    function _min(uint256 a, uint256 b) private pure returns (uint256) {
        return a < b ? a : b;
    }
}
