from curve_stablecoin.interfaces import IMintMonetaryPolicy

DEBT_CANDLE_TIME: constant(uint256) = 86400 // 2

min_debt_candles: public(HashMap[address, IMintMonetaryPolicy.DebtCandle])


@internal
@view
def read(_for: address) -> uint256:
    candle: IMintMonetaryPolicy.DebtCandle = self.min_debt_candles[_for]
    if candle.timestamp == 0:
        return 0

    window_start: uint256 = candle.timestamp // DEBT_CANDLE_TIME * DEBT_CANDLE_TIME
    current_window_end: uint256 = window_start + DEBT_CANDLE_TIME
    next_window_end: uint256 = current_window_end + DEBT_CANDLE_TIME

    if block.timestamp < current_window_end:
        if candle.candle0 > 0:
            return min(candle.candle0, candle.candle1)
        return candle.candle1
    elif block.timestamp < next_window_end:
        return candle.candle1

    return 0


@internal
def write(_for: address, _value: uint256):
    candle: IMintMonetaryPolicy.DebtCandle = self.min_debt_candles[_for]

    if candle.timestamp == 0 and _value == 0:
        return

    window_start: uint256 = candle.timestamp // DEBT_CANDLE_TIME * DEBT_CANDLE_TIME
    current_window_end: uint256 = window_start + DEBT_CANDLE_TIME
    next_window_end: uint256 = current_window_end + DEBT_CANDLE_TIME

    if block.timestamp < current_window_end:
        candle.candle1 = min(candle.candle1, _value)
    elif block.timestamp < next_window_end:
        candle.candle0 = candle.candle1
        candle.candle1 = _value
    else:
        candle.candle0 = _value
        candle.candle1 = _value

    candle.timestamp = block.timestamp
    self.min_debt_candles[_for] = candle