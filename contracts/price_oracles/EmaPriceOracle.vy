# @version 0.3.7
"""
@title EMAPriceOracle - wrapper which adds EMA to a price source for crvUSD
@author Curve.Fi
@license MIT
"""

last_price: public(uint256)
last_timestamp: public(uint256)

MA_EXP_TIME: immutable(uint256)
SIG_ADDRESS: immutable(address)
SIG_METHOD: immutable(Bytes[4])

MIN_MA_EXP_TIME: constant(uint256) = 30
MAX_MA_EXP_TIME: constant(uint256) = 365 * 86400


@external
def __init__(ma_exp_time: uint256,
             _price_oracle_contract:address, _price_oracle_sig: bytes32):
    assert ma_exp_time >= MIN_MA_EXP_TIME
    assert ma_exp_time <= MAX_MA_EXP_TIME
    MA_EXP_TIME = ma_exp_time
    SIG_ADDRESS = _price_oracle_contract
    sig: Bytes[4] = slice(_price_oracle_sig, 28, 4)
    SIG_METHOD = sig

    response: Bytes[32] = raw_call(
        _price_oracle_contract,
        sig,
        is_static_call=True,
        max_outsize=32
    )
    self.last_price = convert(response, uint256)
    self.last_timestamp = block.timestamp


@view
@external
def ma_exp_time() -> uint256:
    return MA_EXP_TIME


@external
@view
def price_oracle_signature() -> (address, Bytes[4]):
    return SIG_ADDRESS, SIG_METHOD


@internal
@view
def _price_oracle() -> uint256:
    response: Bytes[32] = raw_call(
        SIG_ADDRESS,
        SIG_METHOD,
        is_static_call=True,
        max_outsize=32
    )
    return convert(response, uint256)


@external
@view
def ext_price_oracle() -> uint256:
    return self._price_oracle()


@internal
@view
def exp(power: int256) -> uint256:
    if power <= -42139678854452767551:
        return 0

    if power >= 135305999368893231589:
        raise "exp overflow"

    x: int256 = unsafe_div(unsafe_mul(power, 2**96), 10**18)

    k: int256 = unsafe_div(
        unsafe_add(
            unsafe_div(unsafe_mul(x, 2**96), 54916777467707473351141471128),
            2**95),
        2**96)
    x = unsafe_sub(x, unsafe_mul(k, 54916777467707473351141471128))

    y: int256 = unsafe_add(x, 1346386616545796478920950773328)
    y = unsafe_add(unsafe_div(unsafe_mul(y, x), 2**96), 57155421227552351082224309758442)
    p: int256 = unsafe_sub(unsafe_add(y, x), 94201549194550492254356042504812)
    p = unsafe_add(unsafe_div(unsafe_mul(p, y), 2**96), 28719021644029726153956944680412240)
    p = unsafe_add(unsafe_mul(p, x), (4385272521454847904659076985693276 * 2**96))

    q: int256 = x - 2855989394907223263936484059900
    q = unsafe_add(unsafe_div(unsafe_mul(q, x), 2**96), 50020603652535783019961831881945)
    q = unsafe_sub(unsafe_div(unsafe_mul(q, x), 2**96), 533845033583426703283633433725380)
    q = unsafe_add(unsafe_div(unsafe_mul(q, x), 2**96), 3604857256930695427073651918091429)
    q = unsafe_sub(unsafe_div(unsafe_mul(q, x), 2**96), 14423608567350463180887372962807573)
    q = unsafe_add(unsafe_div(unsafe_mul(q, x), 2**96), 26449188498355588339934803723976023)

    return shift(
        unsafe_mul(convert(unsafe_div(p, q), uint256), 3822833074963236453042738258902158003155416615667),
        unsafe_sub(k, 195))


@internal
@view
def ema_price() -> uint256:
    last_timestamp: uint256 = self.last_timestamp
    last_price: uint256 = self.last_price

    if last_timestamp < block.timestamp:
        current_price: uint256 = self._price_oracle()
        alpha: uint256 = self.exp(- convert((block.timestamp - last_timestamp) * 10**18 / MA_EXP_TIME, int256))
        return (current_price * (10**18 - alpha) + last_price * alpha) / 10**18

    else:
        return last_price


@external
@view
def price() -> uint256:
    return self.ema_price()


@external
def price_w() -> uint256:
    p: uint256 = self.ema_price()
    if self.last_timestamp < block.timestamp:
        self.last_price = p
        self.last_timestamp = block.timestamp
    return p
