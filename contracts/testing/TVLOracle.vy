# @version 0.3.9
"""
PoC of a TVL oracle which is using EMA, external to the pools but not manipulatable
"""

interface Pool:
    def get_virtual_price() -> uint256: view  # For crypto pools - better use virtual_price()
    def totalSupply() -> uint256: view


POOL: public(immutable(Pool))
TVL_MA_TIME: public(constant(uint256)) = 600  # In reality will be higher - DEBUG ONLY

last_spot: public(uint256)
last_ema: public(uint256)
last_time: public(uint256)


@external
def __init__(pool: Pool):
    POOL = pool
    self.last_time = block.timestamp
    tvl: uint256 = self._spot_tvl()
    self.last_spot = tvl
    self.last_ema = tvl


@internal
@view
def _spot_tvl() -> uint256:
    return POOL.get_virtual_price() * POOL.totalSupply() / 10**18


@internal
@view
def exp(power: int256) -> uint256:
    if power <= -41446531673892821376:
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
def _ema_tvl() -> uint256[2]:
    last_time: uint256 = self.last_time
    last_spot: uint256 = self.last_spot
    last_ema: uint256 = self.last_ema

    if last_time < block.timestamp:
        alpha: uint256 = self.exp(- convert((block.timestamp - last_time) * 10**18 / TVL_MA_TIME, int256))
        # alpha = 1.0 when dt = 0
        # alpha = 0.0 when dt = inf
        last_ema = (last_spot * (10**18 - alpha) + last_ema * alpha) / 10**18
        last_spot = self._spot_tvl()

    return [last_ema, last_spot]


@external
@view
def ema_tvl() -> uint256:
    return self._ema_tvl()[0]


@external
def ema_tvl_w() -> uint256:
    tvl: uint256[2] = self._ema_tvl()
    self.last_ema = tvl[0]
    self.last_spot = tvl[1]
    self.last_time = block.timestamp
    return tvl[0]
