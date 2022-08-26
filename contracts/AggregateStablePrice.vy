# @version 0.3.6

interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def decimals() -> uint256: view
    def balanceOf(_user: address) -> uint256: view
    def approve(_spender: address, _value: uint256) -> bool: nonpayable


interface Stableswap:
    def price_oracle() -> uint256: view
    def coins(i: uint256) -> address: view
    def balances(i: uint256) -> uint256: view
    def get_virtual_price() -> uint256: view
    def totalSupply() -> uint256: view


struct PricePair:
    pool: Stableswap
    is_inverse: bool


STABLECOIN: immutable(address)
price_pairs: public(PricePair[20])
n_price_pairs: uint256
sigma: public(uint256)


@external
def __init__(stablecoin: address, sigma: uint256):
    STABLECOIN = stablecoin
    self.sigma = sigma  # XXX make a setter


@external
def add_price_pair(_pool: Stableswap):
    price_pair: PricePair = empty(PricePair)
    price_pair.pool = _pool
    coins: address[2] = [_pool.coins(0), _pool.coins(1)]
    if coins[0] == STABLECOIN:
        price_pair.is_inverse = True
    else:
        assert coins[1] == STABLECOIN
    n: uint256 = self.n_price_pairs
    self.price_pairs[n] = price_pair
    self.n_price_pairs = n + 1
    # XXX log


@external
def remove_price_pair(n: uint256):
    n_max: uint256 = self.n_price_pairs - 1
    if n < n_max:
        self.price_pairs[n] = self.price_pairs[n_max]
    self.n_price_pairs = n_max
    # XXX log


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


@external
def price() -> uint256:
    n: uint256 = self.n_price_pairs
    prices: uint256[20] = empty(uint256[20])
    D: uint256[20] = empty(uint256[20])
    Dsum: uint256 = 0
    DPsum: uint256 = 0
    for i in range(20):
        if i == n:
            break
        price_pair: PricePair = self.price_pairs[i]
        p: uint256 = price_pair.pool.price_oracle()
        if price_pair.is_inverse:
            p = 10**18 / p
        prices[i] = p
        _D: uint256 = price_pair.pool.get_virtual_price() * price_pair.pool.totalSupply() / 10**18
        D[i] = _D
        Dsum += _D
        DPsum = _D * p
    p_avg: uint256 = DPsum / Dsum
    e: uint256[20] = empty(uint256[20])
    e_min: uint256 = max_value(uint256)
    sigma: uint256 = self.sigma
    for i in range(20):
        if i == n:
            break
        p: uint256 = prices[i]
        e[i] = (max(p, p_avg) - min(p, p_avg))**2 / sigma * 10**18 / sigma
        e_min = min(e[i], e_min)
    wp_sum: uint256 = 0
    w_sum: uint256 = 0
    for i in range(20):
        if i == n:
            break
        w: uint256 = D[i] * self.exp(-convert(e[i] - e_min, int256))
        w_sum += w
        wp_sum += w * prices[i]
    return wp_sum / w_sum
