# @version 0.3.3

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
def optimized_log2(_x: uint256) -> uint256:
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    res: uint256 = 0
    x: uint256 = _x
    t: uint256 = 2**7
    for i in range(8):
        p: uint256 = pow_mod256(2, t)
        if x >= unsafe_mul(p, 10**18):
            x = unsafe_div(x, p)  # negative shift
            res = unsafe_add(unsafe_mul(t, 10**18), res)
        t = unsafe_div(t, 2)
    d: uint256 = 10**18
    for i in range(34):  # 10 decimals: math.log(10**10, 2) == 33.2. Need more?
        if (x >= 2 * 10**18):
            res = unsafe_add(res, d)
            x = shift(x, -1)  # x /= 2
        x = unsafe_div(unsafe_mul(x, x), 10**18)
        d = shift(d, -1)  # d /= 2
    return res


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
    assert x < MAX_UINT256 / 10**18 + 1
    if x == 0:
        return 0

    z: uint256 = shift(unsafe_add(x, 10**18), -1)
    y: uint256 = x

    for i in range(256):
        if z == y:
            return y
        y = z
        z = shift(unsafe_add(unsafe_div(unsafe_mul(x, 10**18), z), z), -1)

    raise "Did not converge"
