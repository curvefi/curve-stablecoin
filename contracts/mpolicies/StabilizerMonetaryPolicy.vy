# @version 0.3.3
interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def decimals() -> uint256: view
    def balanceOf(_user: address) -> uint256: view

interface PegKeeper:
    def debt() -> uint256: view

interface Pool:
    def coins(i: int128) -> address: view
    def get_dx(i: int128, j: int128, _dy: uint256) -> uint256: view

admin: public(address)

rate0: public(uint256)
halving_shift: public(uint256)  # 10**16

PEG_KEEPER: immutable(address)
POOL: immutable(address)
I_COIN: constant(int128) = 0
I_BASE: constant(int128) = 1
PRECISION_COIN: immutable(uint256)
PRECISION_BASE: immutable(uint256)
EXP_PRECISION: constant(uint256) = 10**10


@external
def __init__(admin: address, peg_keeper: address, pool: address,
             halving_shift: uint256):
    self.admin = admin
    PEG_KEEPER = peg_keeper
    POOL = pool
    PRECISION_COIN = 10 ** (ERC20(Pool(pool).coins(I_COIN)).decimals())
    PRECISION_BASE = 10 ** (ERC20(Pool(pool).coins(I_BASE)).decimals())
    self.halving_shift = halving_shift


@external
def set_admin(admin: address):
    assert msg.sender == self.admin
    self.admin = admin


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
def calculate_rate() -> uint256:
    # Assume that coin 0 is our stablecoin, coin 1 is stablecoin we peg to
    # Calculate how much coin 1 is required to get `debt` of coin 0
    dy: uint256 = PegKeeper(PEG_KEEPER).debt() + 10**18
    dx: uint256 = Pool(POOL).get_dx(1, 0, dy)
    if dx == MAX_UINT256:
        return 0
    # p = dx / dy
    # r = r0 * 2**((1 - p) / h) = r0 * 0.5 ** ((p - 1) / h)
    p: uint256 = dx * PRECISION_BASE * 10**18 / (dy * PRECISION_COIN)
    h: uint256 = self.halving_shift
    r: uint256 = self.rate0
    if p > 10**18:
        r = r * self.halfpow((p - 10**18) * 10**18 / h) / 10**18
    if p < 10**18:
        r = r * 10**18 / self.halfpow((10**18 - p) * 10**18 / h)
    return r


@view
@external
def rate() -> uint256:
    return convert(self.calculate_rate(), uint256)


@external
def rate_write() -> uint256:
    # Not needed here but useful for more authomated policies
    # which change rate0
    return convert(self.calculate_rate(), uint256)


@external
def set_rate(rate: uint256):
    assert msg.sender == self.admin
    self.rate0 = rate
