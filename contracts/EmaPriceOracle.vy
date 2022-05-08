# @version 0.3.3

last_price: public(uint256)
last_timestamp: uint256
EXP_PRECISION: constant(uint256) = 10**10
MA_HALF_TIME: immutable(uint256)
SIG_ADDRESS: immutable(address)
SIG_METHOD: immutable(Bytes[4])


@external
def __init__(ma_half_time: uint256,
             _price_oracle_contract:address, _price_oracle_sig: bytes32):
    MA_HALF_TIME = ma_half_time
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
def ma_half_time() -> uint256:
    return MA_HALF_TIME


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
@pure
def halfpow(power: uint256) -> uint256:
    """
    1e18 * 0.5 ** (power/1e18)

    Inspired by: https://github.com/balancer-labs/balancer-core/blob/master/contracts/BNum.sol#L128
    """
    intpow: uint256 = power / 10**18
    otherpow: uint256 = power - intpow * 10**18
    if intpow > 59:
        return 0
    result: uint256 = 10**18 / (2**intpow)
    if otherpow == 0:
        return result

    term: uint256 = 10**18
    x: uint256 = 5 * 10**17
    S: uint256 = 10**18
    neg: bool = False

    for i in range(1, 256):
        K: uint256 = i * 10**18
        c: uint256 = K - 10**18
        if otherpow > c:
            c = otherpow - c
            neg = not neg
        else:
            c -= otherpow
        term = term * (c * x / 10**18) / K
        if neg:
            S -= term
        else:
            S += term
        if term < EXP_PRECISION:
            return result * S / 10**18

    raise "Did not converge"


@internal
@view
def ema_price() -> uint256:
    last_timestamp: uint256 = self.last_timestamp

    if last_timestamp < block.timestamp:
        last_price: uint256 = self.last_price
        current_price: uint256 = self._price_oracle()
        alpha: uint256 = self.halfpow((block.timestamp - last_timestamp) * 10**18 / MA_HALF_TIME)
        return (last_price * (10**18 - alpha) + current_price * alpha) / 10**18

    else:
        return self.last_price


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
