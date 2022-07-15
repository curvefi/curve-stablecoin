# @version 0.3.4

@view
@external
def pack_ticks(n1: int256, n2: int256) -> int256:
    return min(n1, n2) + max(n1, n2) * 2**128


@view
@external
def unpack_ticks(ns: int256) -> int256[2]:
    n2: int256 = ns / 2**128
    n1: int256 = ns % 2**128
    if n1 >= 2**127:
        n1 -= 2**128
        n2 += 1
    return [n1, n2]
