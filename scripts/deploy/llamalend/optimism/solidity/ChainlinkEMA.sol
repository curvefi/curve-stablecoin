// SPDX-License-Identifier: MIT
// Oracle created by defi.money for their crvUSD fork
// Source: https://github.com/defidotmoney/dfm-contracts

pragma solidity 0.8.25;

interface IChainlinkAggregator {
    function latestRoundData()
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound);

    function getRoundData(uint80 _roundId)
        external
        view
        returns (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound);

    function decimals() external view returns (uint256);
}

interface IPriceOracle {
    function price_w() external returns (uint256);
    function price() external view returns (uint256);
}

contract ChainlinkEMA {
    IChainlinkAggregator public immutable chainlinkFeed;
    uint256 public immutable OBSERVATIONS;
    uint256 public immutable INTERVAL;
    uint256 public immutable SMOOTHING_FACTOR;

    uint256 private immutable MAX_LOOKBACK;

    uint256 public storedPrice;
    uint256 public storedObservationTimestamp;
    ChainlinkResponse public storedResponse;

    struct ChainlinkResponse {
        uint80 roundId;
        uint128 updatedAt;
        uint8 decimals;
        uint256 answer;
    }

    constructor(IChainlinkAggregator _chainlink, uint256 _observations, uint256 _interval) {
        require(_observations > 0 && _interval > 0, "DFM: invalid observations or interval");
        chainlinkFeed = _chainlink;
        OBSERVATIONS = _observations;
        INTERVAL = _interval;
        SMOOTHING_FACTOR = 2e18 / (_observations + 1);
        MAX_LOOKBACK = _observations * 2;

        // round ids without phase bits never trigger the phase check, so load decimals up front
        storedResponse.decimals = _getFeedDecimals();
        uint256 currentObservation = _getCurrentObservationTimestamp();
        (storedPrice, storedResponse) = _calculateNewEMA(currentObservation);
        storedObservationTimestamp = currentObservation;
    }

    function price() external view returns (uint256 currentPrice) {
        uint256 currentObservation = _getCurrentObservationTimestamp();
        uint256 storedObservation = storedObservationTimestamp;
        if (currentObservation == storedObservation) return storedPrice;

        if (storedObservation + MAX_LOOKBACK * INTERVAL > currentObservation) {
            (currentPrice,,) = _calculateLatestEMA(currentObservation, storedObservation);
        } else {
            (currentPrice,) = _calculateNewEMA(currentObservation);
        }
        return currentPrice;
    }

    function price_w() external returns (uint256 currentPrice) {
        uint256 currentObservation = _getCurrentObservationTimestamp();
        uint256 storedObservation = storedObservationTimestamp;
        if (currentObservation == storedObservation) return storedPrice;

        if (storedObservation + MAX_LOOKBACK * INTERVAL > currentObservation) {
            bool isNewResponse;
            ChainlinkResponse memory response;
            (currentPrice, response, isNewResponse) = _calculateLatestEMA(currentObservation, storedObservation);
            if (isNewResponse) storedResponse = response;
        } else {
            (currentPrice, storedResponse) = _calculateNewEMA(currentObservation);
        }
        storedObservationTimestamp = currentObservation;
        storedPrice = currentPrice;
        return currentPrice;
    }

    function _calculateLatestEMA(uint256 currentObservation, uint256 storedObservation)
        internal
        view
        returns (uint256 currentPrice, ChainlinkResponse memory latestResponse, bool isNewResponse)
    {
        currentPrice = storedPrice;
        latestResponse = _getLatestRoundData();
        ChainlinkResponse memory response = storedResponse;

        if (latestResponse.roundId == response.roundId) {
            uint256 answer = response.answer;
            while (storedObservation < currentObservation) {
                storedObservation += INTERVAL;
                currentPrice = _getNextEMA(answer, currentPrice);
            }
            return (currentPrice, latestResponse, false);
        }

        // a new phase aggregator carries rounds from before the switch, walking them forward is unbounded
        if ((latestResponse.roundId >> 64) != (response.roundId >> 64)) {
            (currentPrice, latestResponse) = _calculateNewEMA(currentObservation);
            return (currentPrice, latestResponse, true);
        }

        bool isLatestResponse;
        ChainlinkResponse memory nextResponse;
        if (latestResponse.roundId > response.roundId + 1) {
            nextResponse = _getRoundData(response.roundId + 1, latestResponse.decimals);
        } else {
            nextResponse = latestResponse;
        }

        while (storedObservation < currentObservation) {
            storedObservation += INTERVAL;
            while (!isLatestResponse && nextResponse.updatedAt < storedObservation) {
                response = nextResponse;
                if (nextResponse.roundId == latestResponse.roundId) {
                    isLatestResponse = true;
                } else {
                    nextResponse = _getRoundData(nextResponse.roundId + 1, latestResponse.decimals);
                }
            }
            currentPrice = _getNextEMA(response.answer, currentPrice);
        }

        return (currentPrice, latestResponse, true);
    }

    function _calculateNewEMA(uint256 observationTimestamp)
        internal
        view
        returns (uint256 currentPrice, ChainlinkResponse memory latestResponse)
    {
        latestResponse = _getLatestRoundData();
        ChainlinkResponse memory response = latestResponse;

        uint256[] memory oracleResponses = new uint256[](MAX_LOOKBACK);
        uint256 idx = MAX_LOOKBACK;

        while (true) {
            while (response.updatedAt >= observationTimestamp) {
                if (response.roundId & type(uint64).max == 1) {
                    break;
                }
                response = _getRoundData(response.roundId - 1, latestResponse.decimals);
            }
            if (response.updatedAt >= observationTimestamp) {
                if (idx == MAX_LOOKBACK) {
                    return (response.answer, latestResponse);
                }
                break;
            }
            idx--;
            oracleResponses[idx] = response.answer;
            if (idx == 0) break;
            observationTimestamp -= INTERVAL;
        }

        currentPrice = oracleResponses[idx];
        idx++;
        while (idx < MAX_LOOKBACK) {
            currentPrice = _getNextEMA(oracleResponses[idx], currentPrice);
            idx++;
        }

        return (currentPrice, latestResponse);
    }

    function _getNextEMA(uint256 newPrice, uint256 lastEMA) internal view returns (uint256) {
        return ((newPrice * SMOOTHING_FACTOR) + (lastEMA * (1e18 - SMOOTHING_FACTOR))) / 1e18;
    }

    function _getCurrentObservationTimestamp() internal view returns (uint256) {
        return (block.timestamp / INTERVAL) * INTERVAL;
    }

    function _getLatestRoundData() internal view returns (ChainlinkResponse memory) {
        (uint80 roundId, int256 answer,, uint256 updatedAt,) = chainlinkFeed.latestRoundData();
        // the proxy reports the current aggregator's decimals, so they only change with the phase.
        // Rounds are only ever read from the latest phase, so its decimals apply to all of them
        uint8 decimals = storedResponse.decimals;
        if ((roundId >> 64) != (storedResponse.roundId >> 64)) {
            decimals = _getFeedDecimals();
        }
        return _validateAndFormatResponse(roundId, answer, updatedAt, decimals);
    }

    function _getRoundData(uint80 roundId, uint8 decimals) internal view returns (ChainlinkResponse memory) {
        (uint80 round, int256 answer,, uint256 updatedAt,) = chainlinkFeed.getRoundData(roundId);
        return _validateAndFormatResponse(round, answer, updatedAt, decimals);
    }

    function _getFeedDecimals() internal view returns (uint8) {
        uint256 feedDecimals = chainlinkFeed.decimals();
        require(feedDecimals <= 18, "DFM: Chainlink decimals too high");
        return uint8(feedDecimals);
    }

    function _validateAndFormatResponse(uint80 roundId, int256 answer, uint256 updatedAt, uint8 decimals)
        internal
        pure
        returns (ChainlinkResponse memory)
    {
        require(answer > 0, "DFM: Chainlink answer too low");
        return
            ChainlinkResponse({
                roundId: roundId,
                updatedAt: uint128(updatedAt),
                decimals: decimals,
                answer: uint256(answer) * 10 ** (18 - decimals)
            });
    }
}
