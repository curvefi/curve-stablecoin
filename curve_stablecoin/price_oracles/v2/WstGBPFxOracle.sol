// SPDX-License-Identifier: MIT
// Adapted from WsgemFxLlamalendOracle, Copyright (c) 2026 Arb Capital.
// https://github.com/Arb-Capital/wsgem-llamalend/blob/8596dfa09fb94a832017c65dab536a2e480dbc03/src/WsgemFxLlamalendOracle.sol
pragma solidity 0.8.25;

import {ChainlinkEMA, IChainlinkAggregator, IPriceOracle} from "./ChainlinkEMA.sol";

interface IWstGBP {
    function burncost() external view returns (uint256);
    function pip() external view returns (address);
    function gem() external view returns (address);
    function decimals() external view returns (uint8);
}

/// @notice USD per wstGBP: capped redemption NAV times smoothed GBP/USD. crvUSD is $1.
contract WstGBPFxOracle is IPriceOracle {
    uint256 private constant WAD = 1e18;
    uint256 private constant MAX_QUOTE = 1e36;
    uint256 public constant MAX_ELAPSED = 7 days;
    uint256 public constant MAX_UPSIDE_SPEED = 28_935_185_185; // 0.25% per day
    uint256 public constant MAX_FX_AGE = 30 hours;
    uint256 private constant READ_GAS = 300_000;
    uint256 private constant EMA_READ_GAS = 4_000_000;

    enum Spot {
        PAUSED,
        LIVE_ZERO,
        FX_DOWN,
        QUOTE
    }

    IWstGBP public immutable WSGEM;
    address public immutable GEM;
    address public immutable PIP;
    IChainlinkAggregator public immutable FX_FEED;
    ChainlinkEMA public immutable FX_EMA;
    uint256 public cachedQuote;
    uint256 public cachedTimestamp;
    uint256 public cachedPrice;
    bool public liveZeroReported;
    bool public fxDown;

    event QuoteAnchored(uint256 quote);
    event PriceUpdated(uint256 price);
    event FxDown(uint256 heldPrice);
    event FxRestored(uint256 price);

    constructor(IWstGBP wrapper, IChainlinkAggregator feed, ChainlinkEMA ema) {
        WSGEM = wrapper;
        GEM = wrapper.gem();
        PIP = wrapper.pip();
        FX_FEED = feed;
        FX_EMA = ema;
        require(GEM != address(0) && PIP != address(0), "invalid wrapper");
        require(wrapper.decimals() == 18 && IWstGBP(GEM).decimals() == 18, "invalid decimals");
        require(feed.decimals() == 8 && address(ema.chainlinkFeed()) == address(feed), "invalid feed");
        require(ema.OBSERVATIONS() == 20 && ema.INTERVAL() == 30, "invalid EMA");
        (Spot state, uint256 quote, uint256 fx) = _spot();
        require(state == Spot.QUOTE, "unusable initial price");
        cachedQuote = quote;
        cachedPrice = _compose(quote, fx);
        cachedTimestamp = block.timestamp;
    }

    function price() external view returns (uint256 result) {
        (,, result) = _price();
    }

    function price_w() external returns (uint256 result) {
        (Spot state, uint256 quote, uint256 value) = _price();
        result = value;
        if (state == Spot.QUOTE) {
            // Persist after pricing; a failed write must not change this block's quote.
            address ema = address(FX_EMA);
            bytes4 selector = IPriceOracle.price_w.selector;
            assembly {
                mstore(0, selector)
                pop(call(EMA_READ_GAS, ema, 0, 0, 4, 0, 0))
            }
        }
        cachedTimestamp = block.timestamp;
        if (state == Spot.LIVE_ZERO) {
            liveZeroReported = true;
        } else if (state == Spot.FX_DOWN) {
            if (!fxDown) emit FxDown(result);
            fxDown = true;
        } else if (state == Spot.QUOTE) {
            liveZeroReported = false;
            if (fxDown) emit FxRestored(result);
            fxDown = false;
            if (quote != cachedQuote) {
                cachedQuote = quote;
                emit QuoteAnchored(quote);
            }
            if (result != cachedPrice) {
                cachedPrice = result;
                emit PriceUpdated(result);
            }
        }
    }

    function frozen() external view returns (bool) {
        (Spot state,,) = _spot();
        return state == Spot.PAUSED || state == Spot.FX_DOWN;
    }

    function fxFrozen() external view returns (bool) {
        (Spot state,,) = _spot();
        return state == Spot.FX_DOWN;
    }

    function quoteCeiling() public view returns (uint256) {
        uint256 elapsed = _min(block.timestamp - cachedTimestamp, MAX_ELAPSED);
        return cachedQuote * (WAD + MAX_UPSIDE_SPEED * elapsed) / WAD;
    }

    function _price() private view returns (Spot state, uint256 quote, uint256 result) {
        uint256 fx;
        (state, quote, fx) = _spot();
        quote = _min(quote, quoteCeiling());
        if (state == Spot.LIVE_ZERO || (liveZeroReported && state != Spot.QUOTE)) return (state, quote, 1);
        result = state == Spot.QUOTE ? _compose(quote, fx) : cachedPrice;
    }

    function _spot() private view returns (Spot, uint256, uint256) {
        (bool ok, uint256 quote) = _word(PIP, bytes4(keccak256("read()")), READ_GAS);
        if (!ok || quote == 0) return (Spot.PAUSED, 0, 0);
        (ok, quote) = _word(address(WSGEM), IWstGBP.burncost.selector, READ_GAS);
        if (!ok) return (Spot.PAUSED, 0, 0);
        if (quote == 0) return (Spot.LIVE_ZERO, 0, 0);
        quote = _min(quote, MAX_QUOTE);

        // The EMA has no freshness check; validate the raw feed as well.
        int256 answer;
        uint256 updatedAt;
        address feed = address(FX_FEED);
        bytes4 selector = IChainlinkAggregator.latestRoundData.selector;
        assembly {
            let ptr := mload(0x40)
            mstore(ptr, selector)
            ok := staticcall(READ_GAS, feed, ptr, 4, ptr, 160)
            ok := and(ok, iszero(lt(returndatasize(), 160)))
            answer := mload(add(ptr, 32))
            updatedAt := mload(add(ptr, 96))
        }
        if (!ok || answer <= 0 || answer > 1e26 || updatedAt == 0 || updatedAt > block.timestamp) {
            return (Spot.FX_DOWN, quote, 0);
        }
        if (block.timestamp - updatedAt > MAX_FX_AGE) return (Spot.FX_DOWN, quote, 0);
        uint256 fx;
        (ok, fx) = _word(address(FX_EMA), IPriceOracle.price.selector, EMA_READ_GAS);
        if (!ok || fx == 0 || fx > MAX_QUOTE) return (Spot.FX_DOWN, quote, 0);
        return (Spot.QUOTE, quote, fx);
    }

    // Bounded output and gas let failed or malformed reads take the freeze path.
    function _word(address target, bytes4 selector, uint256 gasLimit) private view returns (bool ok, uint256 value) {
        assembly {
            mstore(0, selector)
            ok := staticcall(gasLimit, target, 0, 4, 0, 32)
            ok := and(ok, iszero(lt(returndatasize(), 32)))
            value := mload(0)
        }
    }

    function _compose(uint256 quote, uint256 fx) private pure returns (uint256) {
        uint256 result = quote * fx / WAD;
        return result == 0 ? 1 : result;
    }

    function _min(uint256 a, uint256 b) private pure returns (uint256) {
        return a < b ? a : b;
    }
}
