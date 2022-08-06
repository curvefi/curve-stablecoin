# @version 0.3.4

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
