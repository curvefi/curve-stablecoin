// SPDX-License-Identifier: MIT
// Adapted from Arb Capital's WsgemFxLlamalendOracle (Copyright (c) 2026 Arb Capital):
// https://github.com/Arb-Capital/wsgem-llamalend/blob/8596dfa09fb94a832017c65dab536a2e480dbc03/src/WsgemFxLlamalendOracle.sol
pragma solidity 0.8.25;

interface IWstGBP {
    function burncost() external view returns (uint256);
    function pip() external view returns (address);
    function gem() external view returns (address);
    function decimals() external view returns (uint8);
}

interface IERC20Decimals {
    function decimals() external view returns (uint8);
}

interface IChainlinkGBPUSD {
    function decimals() external view returns (uint8);
    function latestRoundData()
        external
        view
        returns (uint80, int256, uint256, uint256, uint80);
}

interface IChainlinkEMA {
    function chainlinkFeed() external view returns (address);
    function OBSERVATIONS() external view returns (uint256);
    function INTERVAL() external view returns (uint256);
    function price() external view returns (uint256);
    function price_w() external returns (uint256);
}

/// @notice USD per wstGBP: redemption NAV with capped upside, multiplied by
///         ChainlinkEMA(GBP/USD). crvUSD debt is counted at $1.
/// @dev A paused NAV or unusable FX feed holds the last reported price. The
///      underlying Chainlink round is age-checked because ChainlinkEMA does not
///      enforce staleness. The NAV cap acts before FX conversion.
contract WstGBPFxOracle {
    uint256 internal constant WAD = 1e18;
    uint256 public constant MAX_ELAPSED = 7 days;
    uint256 public constant MAX_UPSIDE_SPEED = 28_935_185_185; // 0.25% per day, WAD/second
    uint256 public constant MAX_FX_AGE = 30 hours;
    uint256 internal constant MAX_QUOTE = 1e36;
    uint256 internal constant READ_GAS = 300_000;
    uint256 internal constant EMA_READ_GAS = 4_000_000;

    IWstGBP public immutable WSGEM;
    address public immutable GEM;
    address public immutable PIP;
    IChainlinkGBPUSD public immutable FX_FEED;
    IChainlinkEMA public immutable FX_EMA;

    uint208 public cachedQuote; // tGBP per wstGBP, rate-limit anchor
    uint40 public cachedTimestamp;
    bool public liveZeroReported;
    uint208 public cachedPrice; // USD per wstGBP, last nonzero report
    bool public fxDown;

    enum Spot { PAUSED, LIVE_ZERO, FX_DOWN, QUOTE }

    event QuoteAnchored(uint256 quote);
    event PriceUpdated(uint256 price);
    event FxDown(uint256 heldPrice);
    event FxRestored(uint256 price);

    constructor(IWstGBP wrapper_, IChainlinkGBPUSD feed_, IChainlinkEMA ema_) {
        require(address(wrapper_) != address(0) && address(feed_) != address(0) && address(ema_) != address(0));
        address gem_ = wrapper_.gem();
        address pip_ = wrapper_.pip();
        require(gem_ != address(0) && pip_ != address(0));
        require(wrapper_.decimals() == 18 && IERC20Decimals(gem_).decimals() == 18);
        require(feed_.decimals() == 8);
        require(ema_.chainlinkFeed() == address(feed_));
        require(ema_.OBSERVATIONS() == 20 && ema_.INTERVAL() == 30);

        WSGEM = wrapper_;
        GEM = gem_;
        PIP = pip_;
        FX_FEED = feed_;
        FX_EMA = ema_;

        (Spot state_, uint256 quote_, uint256 fx_) = _spot();
        require(state_ == Spot.QUOTE, "unusable initial price");
        cachedQuote = uint208(quote_);
        cachedPrice = uint208(_compose(quote_, fx_));
        cachedTimestamp = uint40(block.timestamp);
    }

    function price() external view returns (uint256) {
        (Spot state_, uint256 quote_, uint256 fx_) = _spot();
        return _price(state_, quote_, fx_);
    }

    /// @notice Same-block price as price(); persistence follows the calculation.
    function price_w() external returns (uint256) {
        (Spot state_, uint256 quote_, uint256 fx_) = _spot();
        uint256 limited_;
        uint256 result_;
        if (state_ == Spot.QUOTE) {
            limited_ = _limit(quote_);
            result_ = _compose(limited_, fx_);
            // ChainlinkEMA's write path returns the same value as price() in
            // this block. A write-only failure cannot alter the quoted value.
            try FX_EMA.price_w{gas: EMA_READ_GAS}() returns (uint256) {} catch {}
        } else {
            result_ = _price(state_, quote_, fx_);
        }

        cachedTimestamp = uint40(block.timestamp);
        if (state_ == Spot.LIVE_ZERO) {
            liveZeroReported = true;
        } else if (state_ == Spot.FX_DOWN) {
            if (!fxDown) emit FxDown(result_);
            fxDown = true;
        } else if (state_ == Spot.QUOTE) {
            liveZeroReported = false;
            if (fxDown) emit FxRestored(result_);
            fxDown = false;
            if (limited_ != cachedQuote) {
                cachedQuote = uint208(limited_);
                emit QuoteAnchored(limited_);
            }
            if (result_ != cachedPrice) {
                cachedPrice = uint208(result_);
                emit PriceUpdated(result_);
            }
        }
        return result_;
    }

    function frozen() external view returns (bool) {
        (Spot state_,,) = _spot();
        return state_ == Spot.PAUSED || state_ == Spot.FX_DOWN;
    }

    function fxFrozen() external view returns (bool) {
        (Spot state_,,) = _spot();
        return state_ == Spot.FX_DOWN;
    }

    function quoteCeiling() external view returns (uint256) {
        return _ceiling();
    }

    function _spot() internal view returns (Spot, uint256, uint256) {
        (bool okNav_, uint256 nav_) = _readWord(PIP, abi.encodeWithSignature("read()"), READ_GAS);
        if (!okNav_ || nav_ == 0) return (Spot.PAUSED, 0, 0);

        (bool okQuote_, uint256 quote_) = _readWord(address(WSGEM), abi.encodeCall(IWstGBP.burncost, ()), READ_GAS);
        if (!okQuote_) return (Spot.PAUSED, 0, 0);
        if (quote_ == 0) return (Spot.LIVE_ZERO, 0, 0);
        quote_ = quote_ > MAX_QUOTE ? MAX_QUOTE : quote_;

        (bool okFx_, uint256 fx_) = _readFx();
        if (!okFx_) return (Spot.FX_DOWN, quote_, 0);
        return (Spot.QUOTE, quote_, fx_);
    }

    function _readFx() internal view returns (bool, uint256) {
        bytes memory callData_ = abi.encodeCall(IChainlinkGBPUSD.latestRoundData, ());
        bool ok_;
        uint256 size_;
        int256 answer_;
        uint256 updatedAt_;
        address feed_ = address(FX_FEED);
        assembly ("memory-safe") {
            let out_ := mload(0x40)
            ok_ := staticcall(READ_GAS, feed_, add(callData_, 0x20), mload(callData_), out_, 0xa0)
            size_ := returndatasize()
            answer_ := mload(add(out_, 0x20))
            updatedAt_ := mload(add(out_, 0x60))
        }
        // The raw feed has eight decimals; reject an implausible round before
        // consulting the EMA, which may still be near its previous value.
        if (!ok_ || size_ < 0xa0 || answer_ <= 0 || answer_ > 1e26 || updatedAt_ == 0 || updatedAt_ > block.timestamp) {
            return (false, 0);
        }
        if (block.timestamp - updatedAt_ > MAX_FX_AGE) return (false, 0);

        (bool okEma_, uint256 fx_) = _readWord(address(FX_EMA), abi.encodeCall(IChainlinkEMA.price, ()), EMA_READ_GAS);
        if (!okEma_ || fx_ == 0 || fx_ > MAX_QUOTE) return (false, 0);
        return (true, fx_);
    }

    function _readWord(address target_, bytes memory data_, uint256 gas_) internal view returns (bool ok_, uint256 word_) {
        uint256 size_;
        assembly ("memory-safe") {
            ok_ := staticcall(gas_, target_, add(data_, 0x20), mload(data_), 0x00, 0x20)
            size_ := returndatasize()
            word_ := mload(0x00)
        }
        if (!ok_ || size_ < 32) return (false, 0);
    }

    function _price(Spot state_, uint256 quote_, uint256 fx_) internal view returns (uint256) {
        if (state_ == Spot.PAUSED || state_ == Spot.FX_DOWN) {
            return liveZeroReported ? 1 : cachedPrice;
        }
        if (state_ == Spot.LIVE_ZERO) return 1;
        return _compose(_limit(quote_), fx_);
    }

    function _limit(uint256 quote_) internal view returns (uint256) {
        uint256 ceiling_ = _ceiling();
        return quote_ < ceiling_ ? quote_ : ceiling_;
    }

    function _ceiling() internal view returns (uint256) {
        uint256 elapsed_ = block.timestamp - cachedTimestamp;
        if (elapsed_ > MAX_ELAPSED) elapsed_ = MAX_ELAPSED;
        return uint256(cachedQuote) * (WAD + MAX_UPSIDE_SPEED * elapsed_) / WAD;
    }

    function _compose(uint256 quote_, uint256 fx_) internal pure returns (uint256) {
        uint256 value_ = quote_ * fx_ / WAD; // both legs <= 1e36
        return value_ == 0 ? 1 : value_;
    }
}
