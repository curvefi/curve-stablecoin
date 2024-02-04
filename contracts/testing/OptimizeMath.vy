# @version 0.3.10

EXP_PRECISION: constant(uint256) = 10**10


@external
@view
def original_log2(_x: uint256) -> uint256:
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    res: uint256 = 0
    x: uint256 = _x
    for i in range(8):
        t: uint256 = 2**(7 - i)
        p: uint256 = 2**t
        if x >= p * 10**18:
            x /= p
            res += t * 10**18
    d: uint256 = 10**18
    for i in range(34):  # 10 decimals: math.log(10**10, 2) == 33.2. Need more?
        if (x >= 2 * 10**18):
            res += d
            x /= 2
        x = x * x / 10**18
        d /= 2
    return res


@external
@view
def optimized_log2(_x: uint256) -> int256:
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    inverse: bool = _x < 10**18
    res: uint256 = 0
    x: uint256 = _x
    if inverse:
        x = 10**36 / x
    t: uint256 = 2**7
    for i in range(8):
        p: uint256 = pow_mod256(2, t)
        if x >= unsafe_mul(p, 10**18):
            x = unsafe_div(x, p)
            res = unsafe_add(unsafe_mul(t, 10**18), res)
        t = unsafe_div(t, 2)
    d: uint256 = 10**18
    for i in range(34):  # 10 decimals: math.log(10**10, 2) == 33.2. Need more?
        if (x >= 2 * 10**18):
            res = unsafe_add(res, d)
            x = unsafe_div(x, 2)
        x = unsafe_div(unsafe_mul(x, x), 10**18)
        d = unsafe_div(d, 2)
    if inverse:
        return -convert(res, int256)
    else:
        return convert(res, int256)


@external
@view
def original_sqrt(x: uint256) -> uint256:
    """
    Originating from: https://github.com/vyperlang/vyper/issues/1266
    """

    if x == 0:
        return 0

    z: uint256 = (x + 10**18) / 2
    y: uint256 = x

    for i in range(256):
        if z == y:
            return y
        y = z
        z = (x * 10**18 / z + z) / 2

    raise "Did not converge"


@external
@view
def optimized_sqrt(x: uint256) -> uint256:
    """
    Originating from: https://github.com/vyperlang/vyper/issues/1266
    """
    assert x < max_value(uint256) / 10**18 + 1
    if x == 0:
        return 0

    z: uint256 = unsafe_div(unsafe_add(x, 10**18), 2)
    y: uint256 = x

    for i in range(256):
        if z == y:
            return y
        y = z
        z = unsafe_div(unsafe_add(unsafe_div(unsafe_mul(x, 10**18), z), z), 2)

    raise "Did not converge"


@external
@view
def optimized_sqrt_initial(x: uint256, y0: uint256) -> uint256:
    """
    Originating from: https://github.com/vyperlang/vyper/issues/1266
    """
    if x == 0:
        return 0
    _x: uint256 = x * 10**18

    z: uint256 = y0
    y: uint256 = 0
    if z == 0:
        z = unsafe_div(unsafe_add(x, 10**18), 2)

    for i in range(256):
        z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
        if z == y:
            return y
        y = z

    raise "Did not converge"

@external
@view
def optimized_sqrt_solmate(x: uint256) -> uint256:
    # https://github.com/transmissions11/solmate/blob/v7/src/utils/FixedPointMathLib.sol#L288
    _x: uint256 = x * 10**18
    y: uint256 = _x
    z: uint256 = 181
    if y >= 2**(128 + 8):
        y = unsafe_div(y, 2**128)
        z = unsafe_mul(z, 2**64)
    if y >= 2**(64 + 8):
        y = unsafe_div(y, 2**64)
        z = unsafe_mul(z, 2**32)
    if y >= 2**(32 + 8):
        y = unsafe_div(y, 2**32)
        z = unsafe_mul(z, 2**16)
    if y >= 2**(16 + 8):
        y = unsafe_div(y, 2**16)
        z = unsafe_mul(z, 2**8)

    z = unsafe_div(unsafe_mul(z, unsafe_add(y, 65536)), 2**18)

    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    return unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)


@external
@view
def halfpow(power: uint256) -> uint256:
    """
    1e18 * 0.5 ** (power/1e18)

    Inspired by: https://github.com/balancer-labs/balancer-core/blob/master/contracts/BNum.sol#L128

    Better result can by achived with:
    https://github.com/transmissions11/solmate/blob/v7/src/utils/FixedPointMathLib.sol#L34
    """
    intpow: uint256 = unsafe_div(power, 10**18)
    if intpow > 59:
        return 0
    otherpow: uint256 = unsafe_sub(power, unsafe_mul(intpow, 10**18))  # < 10**18
    result: uint256 = unsafe_div(10**18, pow_mod256(2, intpow))
    if otherpow == 0:
        return result

    term: uint256 = 10**18
    S: uint256 = 10**18
    c: uint256 = otherpow

    for i in range(1, 256):
        K: uint256 = unsafe_mul(i, 10**18)  # <= 255 * 10**18; >= 10**18
        term = unsafe_div(unsafe_mul(term, unsafe_div(c, 2)), K)
        S = unsafe_sub(S, term)
        if term < EXP_PRECISION:
            return unsafe_div(unsafe_mul(result, S), 10**18)
        c = unsafe_sub(K, otherpow)

    raise "Did not converge"


@external
@view
def optimized_exp(power: int256) -> uint256:
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
@pure
def _log_2(x: uint256) -> uint256:
    """
    @dev An `internal` helper function that returns the log in base 2
         of `x`, following the selected rounding direction.
    @notice Note that it returns 0 if given 0. The implementation is
            inspired by OpenZeppelin's implementation here:
            https://github.com/OpenZeppelin/openzeppelin-contracts/blob/master/contracts/utils/math/Math.sol.
            This code is taken from snekmate.
    @param x The 32-byte variable.
    @return uint256 The 32-byte calculation result.
    """
    value: uint256 = x
    result: uint256 = empty(uint256)

    # The following lines cannot overflow because we have the well-known
    # decay behaviour of `log_2(max_value(uint256)) < max_value(uint256)`.
    if (x >> 128 != empty(uint256)):
        value = x >> 128
        result = 128
    if (value >> 64 != empty(uint256)):
        value = value >> 64
        result = unsafe_add(result, 64)
    if (value >> 32 != empty(uint256)):
        value = value >> 32
        result = unsafe_add(result, 32)
    if (value >> 16 != empty(uint256)):
        value = value >> 16
        result = unsafe_add(result, 16)
    if (value >> 8 != empty(uint256)):
        value = value >> 8
        result = unsafe_add(result, 8)
    if (value >> 4 != empty(uint256)):
        value = value >> 4
        result = unsafe_add(result, 4)
    if (value >> 2 != empty(uint256)):
        value = value >> 2
        result = unsafe_add(result, 2)
    if (value >> 1 != empty(uint256)):
        result = unsafe_add(result, 1)

    return result


@external
@pure
def wad_ln(x: uint256) -> int256:
    """
    @dev Calculates the natural logarithm of a signed integer with a
         precision of 1e18.
    @notice Note that it returns 0 if given 0. Furthermore, this function
            consumes about 1,400 to 1,650 gas units depending on the value
            of `x`. The implementation is inspired by Remco Bloemen's
            implementation under the MIT license here:
            https://xn--2-umb.com/22/exp-ln.
            This code is taken from snekmate.
    @param x The 32-byte variable.
    @return int256 The 32-byte calculation result.
    """
    value: int256 = convert(x, int256)

    assert x > 0

    # We want to convert `x` from "10 ** 18" fixed point to "2 ** 96"
    # fixed point. We do this by multiplying by "2 ** 96 / 10 ** 18".
    # But since "ln(x * C) = ln(x) + ln(C)" holds, we can just do nothing
    # here and add "ln(2 ** 96 / 10 ** 18)" at the end.

    # Reduce the range of `x` to "(1, 2) * 2 ** 96".
    # Also remember that "ln(2 ** k * x) = k * ln(2) + ln(x)" holds.
    k: int256 = unsafe_sub(convert(self._log_2(x), int256), 96)
    # Note that to circumvent Vyper's safecast feature for the potentially
    # negative expression `value <<= uint256(159 - k)`, we first convert the
    # expression `value <<= uint256(159 - k)` to `bytes32` and subsequently
    # to `uint256`. Remember that the EVM default behaviour is to use two's
    # complement representation to handle signed integers.
    value = convert(convert(convert(value << convert(unsafe_sub(159, k), uint256), bytes32), uint256) >> 159, int256)

    # Evaluate using a "(8, 8)"-term rational approximation. Since `p` is monic,
    # we will multiply by a scaling factor later.
    p: int256 = unsafe_add(unsafe_mul(unsafe_add(value, 3_273_285_459_638_523_848_632_254_066_296), value) >> 96, 24_828_157_081_833_163_892_658_089_445_524)
    p = unsafe_add(unsafe_mul(p, value) >> 96, 43_456_485_725_739_037_958_740_375_743_393)
    p = unsafe_sub(unsafe_mul(p, value) >> 96, 11_111_509_109_440_967_052_023_855_526_967)
    p = unsafe_sub(unsafe_mul(p, value) >> 96, 45_023_709_667_254_063_763_336_534_515_857)
    p = unsafe_sub(unsafe_mul(p, value) >> 96, 14_706_773_417_378_608_786_704_636_184_526)
    p = unsafe_sub(unsafe_mul(p, value), 795_164_235_651_350_426_258_249_787_498 << 96)

    # We leave `p` in the "2 ** 192" base so that we do not have to scale it up
    # again for the division. Note that `q` is monic by convention.
    q: int256 = unsafe_add(unsafe_mul(unsafe_add(value, 5_573_035_233_440_673_466_300_451_813_936), value) >> 96, 71_694_874_799_317_883_764_090_561_454_958)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 283_447_036_172_924_575_727_196_451_306_956)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 401_686_690_394_027_663_651_624_208_769_553)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 204_048_457_590_392_012_362_485_061_816_622)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 31_853_899_698_501_571_402_653_359_427_138)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 909_429_971_244_387_300_277_376_558_375)

    # It is known that the polynomial `q` has no zeros in the domain.
    # No scaling is required, as `p` is already "2 ** 96" too large. Also,
    # `r` is in the range "(0, 0.125) * 2 ** 96" after the division.
    r: int256 = unsafe_div(p, q)

    # To finalise the calculation, we have to proceed with the following steps:
    #   - multiply by the scaling factor "s = 5.549...",
    #   - add "ln(2 ** 96 / 10 ** 18)",
    #   - add "k * ln(2)", and
    #   - multiply by "10 ** 18 / 2 ** 96 = 5 ** 18 >> 78".
    # In order to perform the most gas-efficient calculation, we carry out all
    # these steps in one expression.
    return unsafe_add(unsafe_add(unsafe_mul(r, 1_677_202_110_996_718_588_342_820_967_067_443_963_516_166),\
           unsafe_mul(k, 16_597_577_552_685_614_221_487_285_958_193_947_469_193_820_559_219_878_177_908_093_499_208_371)),\
           600_920_179_829_731_861_736_702_779_321_621_459_595_472_258_049_074_101_567_377_883_020_018_308) >> 174
