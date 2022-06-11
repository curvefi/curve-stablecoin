# @version 0.3.3

interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def decimals() -> uint256: view
    def balanceOf(_user: address) -> uint256: view

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


event TokenExchange:
    buyer: indexed(address)
    sold_id: uint256
    tokens_sold: uint256
    bought_id: uint256
    tokens_bought: uint256

event Deposit:
    provider: indexed(address)
    amount: uint256
    n1: int256
    n2: int256

event Withdraw:
    provider: indexed(address)
    receiver: address
    amount_borrowed: uint256
    amount_collateral: uint256

event SetRate:
    rate: int256
    rate_mul: uint256
    time: uint256

event SetFee:
    fee: uint256


MAX_INT: constant(int256) = 2**254 + (2**254 - 1)  # 2**255 - 1
MAX_TICKS: constant(int256) = 50

struct UserTicks:
    ns: bytes32  # packs n1 and n2, each is int128
    ticks: uint256[MAX_TICKS/2]  # Share fractions packed 2 per slot

struct DetailedTrade:
    in_amount: uint256
    out_amount: uint256
    n1: int256
    n2: int256
    ticks_in: uint256[MAX_TICKS]
    last_tick_j: uint256

BORROWED_TOKEN: immutable(ERC20)    # x
BORROWED_PRECISION: immutable(uint256)

collateral_token: public(ERC20)  # y
collateral_precision: public(uint256)

A: public(uint256)
sqrt_band_ratio: public(uint256)  # sqrt(A / (A - 1))
base_price: uint256
fee: public(uint256)
admin_fee: public(uint256)
rate: public(int256)  # Rate can be negative, to support positive-rebase tokens
rate_time: uint256
rate_mul: public(uint256)
active_band: public(int256)
min_band: int256
max_band: int256

price_oracle_contract: public(PriceOracle)

p_base_mul: public(uint256)

bands_x: public(HashMap[int256, uint256])
bands_y: public(HashMap[int256, uint256])

total_shares: HashMap[int256, uint256]
user_shares: HashMap[address, UserTicks]

admin: public(address)


@external
def __init__(_borrowed_token: address):
    BORROWED_TOKEN = ERC20(_borrowed_token)
    BORROWED_PRECISION = 10 ** (18 - ERC20(_borrowed_token).decimals())


# Low-level math
@internal
@pure
def sqrt_int(x: uint256) -> uint256:
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
# End of low-level math


@external
def initialize(
    _A: uint256,
    _base_price: uint256,
    _collateral_token: address,
    fee: uint256,
    admin_fee: uint256,
    _price_oracle_contract: address,
    _admin: address
    ):
    assert self.A == 0
    assert _A > 0

    self.A = _A
    self.base_price = _base_price
    self.rate_time = block.timestamp
    self.rate_mul = 10**18
    self.p_base_mul = 10**18
    self.collateral_token = ERC20(_collateral_token)
    self.collateral_precision = pow_mod256(10, 18 - ERC20(_collateral_token).decimals())
    self.fee = fee
    self.admin_fee = admin_fee

    self.price_oracle_contract = PriceOracle(_price_oracle_contract)
    self.sqrt_band_ratio = self.sqrt_int(unsafe_mul(10**18, _A) / unsafe_sub(_A, 1))

    self.admin = _admin


@external
@view
def price_oracle() -> uint256:
    return self.price_oracle_contract.price()


@internal
@view
def _rate_mul() -> uint256:
    return convert(convert(self.rate_mul, int256) + self.rate * convert(block.timestamp - self.rate_time, int256), uint256)


@external
@view
def get_rate_mul() -> uint256:
    return self._rate_mul()


@internal
@view
def _base_price() -> uint256:
    """
    Base price grows with time to account for interest rate (which is 0 by default)
    """
    return self.base_price * self._rate_mul() / 10**18


@external
@view
def get_base_price() -> uint256:
    return self._base_price()


@internal
@view
def _p_oracle_band(n: int256, is_down: bool) -> uint256:
    # k = (self.A - 1) / self.A  # equal to (p_up / p_down)
    # return self.p_base * k ** n
    n_active: int256 = self.active_band
    p_base: uint256 = unsafe_div(self._base_price() * self.p_base_mul, 10**18)
    band_distance: uint256 = convert(abs(n - n_active), uint256)
    assert band_distance < 1024, "Too deep"
    A: uint256 = self.A

    # k = (self.A - 1) / self.A  # equal to (p_up / p_down)
    # p_base = self.p_base * k ** (n_band + 1)
    m: uint256 = 1
    amul: uint256 = 0
    if n > n_active:
        amul = unsafe_div(10**18 * unsafe_sub(A, 1), A)  # (A - 1) / A
    else:
        amul = unsafe_mul(10**18, A) / unsafe_sub(A, 1)  # A / (A - 1)
    for i in range(1, 12):
        if m > band_distance:
            if is_down:
                return unsafe_div(p_base * unsafe_sub(A, 1), A)  # p_base * (A - 1) / A
            else:
                return p_base
        if bitwise_and(band_distance, m) > 0:
            p_base = unsafe_div(p_base * amul, 10**18)
        m = unsafe_add(m, m)  # m *= 2
        amul = unsafe_div(amul * amul, 10**18)  # amul = amul**2
    raise


@internal
@view
def _p_current_band(n: int256, is_up: bool) -> uint256:
    """
    Upper or lower price of the band `n` at current `p_oracle`
    """
    # k = (self.A - 1) / self.A  # equal to (p_up / p_down)
    # p_base = self.p_base * k ** (n_band + 1)
    p_base: uint256 = self._p_oracle_band(n, is_up)

    # return self.p_oracle**3 / p_base**2
    p_oracle: uint256 = self.price_oracle_contract.price()
    return p_oracle**2 / p_base * p_oracle / p_base


@external
@view
def p_current_up(n: int256) -> uint256:
    """
    Upper price of the band `n` at current `p_oracle`
    """
    return self._p_current_band(n, True)


@external
@view
def p_current_down(n: int256) -> uint256:
    """
    Lower price of the band `n` at current `p_oracle`
    """
    return self._p_current_band(n, False)


@external
@view
def p_oracle_up(n: int256) -> uint256:
    """
    Upper price of the band `n` when `p_oracle` == `p`
    """
    return self._p_oracle_band(n, False)


@external
@view
def p_oracle_down(n: int256) -> uint256:
    """
    Lower price of the band `n` when `p_oracle` == `p`
    """
    return self._p_oracle_band(n, True)


@internal
@view
def _get_y0(x: uint256, y: uint256, p_o: uint256, p_o_up: uint256, A: uint256) -> uint256:
    # solve:
    # p_o * A * y0**2 - y0 * (p_oracle_up/p_o * (A-1) * x + p_o**2/p_oracle_up * A * y) - xy = 0
    b: uint256 = 0
    # p_o_up * unsafe_sub(A, 1) * x / p_o + A * p_o**2 / p_o_up * y / 10**18
    if x > 0:
        b = p_o_up * unsafe_sub(A, 1) * x / p_o
    if y > 0:
        b += A * p_o**2 / p_o_up * y / 10**18
    if x > 0 and y > 0:
        D: uint256 = b**2 + (4 * A) * p_o * y / 10**18 * x
        return (b + self.sqrt_int(D / 10**18)) * 10**18 / ((2 * A) * p_o)
    else:
        return b * 10**18 / (A * p_o)


@external
@view
def get_y0(n: int256) -> uint256:
    x: uint256 = self.bands_x[n]
    y: uint256 = self.bands_y[n]
    p_o: uint256 = self.price_oracle_contract.price()
    p_oracle_up: uint256 = 0
    if n == MAX_INT:
        p_oracle_up = self._base_price() * self.p_base_mul / 10**18
    else:
        p_oracle_up = self._p_oracle_band(n, False)

    return self._get_y0(x, y, p_o, p_oracle_up, self.A)


@internal
@view
def _get_p(n: int256, x: uint256, y: uint256) -> uint256:
    p_o_up: uint256 = self._p_oracle_band(n, False)
    p_o: uint256 = self.price_oracle_contract.price()
    A: uint256 = self.A

    # Special cases
    if x == 0 and y == 0:
        p_o_up = unsafe_div(p_o_up * unsafe_sub(A, 1), A)
        return p_o**2 / p_o_up * p_o / p_o_up * 10**18 / self.sqrt_band_ratio
    if x == 0: # Lowest point of this band -> p_current_down
        return p_o**2 / p_o_up * p_o / p_o_up
    if y == 0: # Highest point of this band -> p_current_up
        p_o_up = unsafe_div(p_o_up * unsafe_sub(A, 1), A)
        return p_o**2 / p_o_up * p_o / p_o_up

    y0: uint256 = self._get_y0(x, y, p_o, p_o_up, A)

    # (f(y0) + x) / (g(y0) + y)
    f: uint256 = A * y0 * p_o / p_o_up * p_o
    g: uint256 = unsafe_sub(A, 1) * y0 * p_o_up / p_o
    return (f + x * 10**18) / (g + y)


@external
@view
def get_p() -> uint256:
    n: int256 = self.active_band
    return self._get_p(n, self.bands_x[n], self.bands_y[n])


@internal
def save_user_ticks(user: address, n1: int256, n2: int256, ticks: uint256[MAX_TICKS], save_n: bool):
    """
    Packs and saves user ticks
    """
    if save_n:
        n1p: uint256 = convert(convert(convert(n1, int128), bytes32), uint256)
        n2p: uint256 = convert(convert(convert(n2, int128), bytes32), uint256)
        if n1 > n2:
            self.user_shares[user].ns = convert(bitwise_or(n2p, shift(n1p, 128)), bytes32)
        else:
            self.user_shares[user].ns = convert(bitwise_or(n1p, shift(n2p, 128)), bytes32)

    dist: uint256 = convert(abs(n1 - n2), uint256) + 1
    ptr: uint256 = 0
    for i in range(MAX_TICKS / 2):
        if ptr >= dist:
            break
        tick: uint256 = ticks[ptr]
        ptr += 1
        if dist != ptr:
            tick = bitwise_or(tick, shift(ticks[ptr], 128))
        ptr += 1
        self.user_shares[user].ticks[i] = tick


@internal
@view
def _read_user_tick_numbers(user: address) -> int256[2]:
    """
    Unpacks and reads user tick numbers
    """
    ns: uint256 = convert(self.user_shares[user].ns, uint256)
    n1: int256 = convert(convert(convert(bitwise_and(ns, 2**128 - 1), bytes32), int128), int256)
    n2: int256 = convert(convert(convert(shift(ns, -128), bytes32), int128), int256)
    return [n1, n2]


@external
@view
def read_user_tick_numbers(user: address) -> int256[2]:
    return self._read_user_tick_numbers(user)


@internal
@view
def _read_user_ticks(user: address, size: int256) -> uint256[MAX_TICKS]:
    """
    Unpacks and reads user ticks
    """
    ticks: uint256[MAX_TICKS] = empty(uint256[MAX_TICKS])
    ptr: int256 = 0
    for i in range(MAX_TICKS / 2):
        if ptr + 1 > size:
            break
        tick: uint256 = self.user_shares[user].ticks[i]
        ticks[ptr] = bitwise_and(tick, 2**128 - 1)
        ptr += 1
        if ptr != size:
            ticks[ptr] = shift(tick, -128)
        ptr += 1
    return ticks


@external
@nonreentrant('lock')
def deposit_range(user: address, amount: uint256, n1: int256, n2: int256, move_coins: bool):
    assert msg.sender == self.admin
    collateral_precision: uint256 = self.collateral_precision

    n0: int256 = self.active_band
    assert n1 > n0 and n2 > n0, "Deposits should be below current band"
    if move_coins:
        assert self.collateral_token.transferFrom(user, self, amount)

    band: int256 = max(n1, n2)  # Fill from high N to low N
    finish: int256 = min(n1, n2)
    i: uint256 = convert(band - finish, uint256)
    n_bands: uint256 = i + 1

    y: uint256 = amount * collateral_precision / n_bands
    assert y > 100, "Amount too low"

    save_n: bool = True
    if self.user_shares[user].ticks[0] != 0:  # Has liquidity
        ns: int256[2] = self._read_user_tick_numbers(user)
        assert ns[0] == finish and ns[1] == band, "Wrong range"
        save_n = False

    user_shares: uint256[MAX_TICKS] = empty(uint256[MAX_TICKS])

    for j in range(MAX_TICKS):
        if i == 0:
            # Take the dust in the last band
            # Maybe could give up on this though
            y = amount * collateral_precision - y * (n_bands - 1)
        # Deposit coins
        assert self.bands_x[band] == 0, "Band not empty"
        total_y: uint256 = self.bands_y[band]
        self.bands_y[band] = total_y + y
        # Total / user share
        s: uint256 = self.total_shares[band]
        if s == 0:
            assert y < 2**128
            s = y
            user_shares[i] = y
        else:
            ds: uint256 = s * y / total_y
            assert ds > 0, "Amount too low"
            user_shares[i] = ds
            s += ds
        self.total_shares[band] = s
        # End the cycle
        band -= 1
        if i == 0:
            break
        i -= 1

    self.min_band = min(self.min_band, n1)
    self.max_band = max(self.max_band, n2)
    self.save_user_ticks(user, n1, n2, user_shares, save_n)

    self.rate_mul = self._rate_mul()
    self.rate_time = block.timestamp

    log Deposit(user, amount, n1, n2)


@external
@nonreentrant('lock')
def withdraw(user: address, move_to: address) -> uint256[2]:
    assert msg.sender == self.admin

    ns: int256[2] = self._read_user_tick_numbers(user)
    user_shares: uint256[MAX_TICKS] = self._read_user_ticks(user, ns[1] - ns[0] + 1)
    assert user_shares[0] > 0, "No deposits"

    total_x: uint256 = 0
    total_y: uint256 = 0
    min_band: int256 = self.min_band
    old_min_band: int256 = min_band
    max_band: int256 = 0

    for i in range(MAX_TICKS):
        x: uint256 = self.bands_x[ns[0]]
        y: uint256 = self.bands_y[ns[0]]
        ds: uint256 = user_shares[i]
        s: uint256 = self.total_shares[ns[0]]
        dx: uint256 = x * ds / s
        dy: uint256 = y * ds / s

        self.total_shares[ns[0]] = s - ds
        x -= dx
        y -= dy
        if ns[0] == min_band and x == 0 and y == 0:
            min_band += 1
        if x > 0 or y > 0:
            max_band = ns[0]
        self.bands_x[ns[0]] = x
        self.bands_y[ns[0]] = y
        total_x += dx
        total_y += dy

        ns[0] += 1
        if ns[0] > ns[1]:
            break

    # Empty the ticks
    self.user_shares[user].ticks[0] = 0

    if old_min_band != min_band:
        self.min_band = min_band
    if self.max_band <= ns[1]:
        self.max_band = max_band

    total_x = unsafe_div(total_x, BORROWED_PRECISION)
    total_y = unsafe_div(total_y, self.collateral_precision)
    if move_to != ZERO_ADDRESS:
        assert BORROWED_TOKEN.transfer(move_to, total_x)
        assert self.collateral_token.transfer(move_to, total_y)
    log Withdraw(user, move_to, total_x, total_y)

    self.rate_mul = self._rate_mul()
    self.rate_time = block.timestamp

    return [total_x, total_y]


@external
def rugpull(coin: address, _to: address, val: uint256):
    assert msg.sender == self.admin

    if val > 0:
        assert ERC20(coin).transfer(_to, val)


@internal
@view
def calc_swap_out(pump: bool, in_amount: uint256, p_o: uint256) -> DetailedTrade:
    out: DetailedTrade = empty(DetailedTrade)
    # pump = True: borrowable (USD) in, collateral (ETH) out; going up
    # pump = False: collateral (ETH) in, borrowable (USD) out; going down
    out.n1 = self.active_band
    out.n2 = out.n1
    p_o_up: uint256 = self._base_price() * self.p_base_mul / 10**18
    fee: uint256 = self.fee
    admin_fee: uint256 = self.admin_fee
    in_amount_afee: uint256 = in_amount * fee / 10**18 * admin_fee / 10**18
    in_amount_left: uint256 = in_amount - in_amount_afee
    in_amount_used: uint256 = 0
    fee = (10**18)**2 / (10**18 - fee)
    x: uint256 = self.bands_x[out.n2]
    y: uint256 = self.bands_y[out.n2]
    min_band: int256 = self.min_band
    max_band: int256 = self.max_band
    collateral_precision: uint256 = self.collateral_precision
    A: uint256 = self.A

    for i in range(MAX_TICKS):
        y0: uint256 = self._get_y0(x, y, p_o, p_o_up, A)
        f: uint256 = A * y0 * p_o / p_o_up * p_o / 10**18
        g: uint256 = unsafe_sub(A, 1) * y0 * p_o_up / p_o
        Inv: uint256 = (f + x) * (g + y)

        if pump:
            if y > 0 and g > 0:
                x_dest: uint256 = Inv / g - f
                if (x_dest - x) * fee / 10**18 >= in_amount_left:
                    # This is the last band
                    out.last_tick_j = Inv / (f + (x + in_amount_left * 10**18 / fee)) - g  # Should be always >= 0
                    x += in_amount_left  # x is precise after this
                    # Round down the output
                    out.out_amount += unsafe_mul(unsafe_div(y - out.last_tick_j, collateral_precision), collateral_precision)
                    out.ticks_in[i] = x
                    out.in_amount = in_amount
                    return out

                else:
                    # We go into the next band
                    dx: uint256 = (x_dest - x) * fee / 10**18
                    in_amount_left -= dx
                    out.ticks_in[i] = x + dx
                    in_amount_used += dx
                    out.out_amount += y

            if i != MAX_TICKS - 1:
                if out.n2 == max_band:
                    break
                out.n2 += 1
                p_o_up = unsafe_div(p_o_up * unsafe_sub(A, 1), A)
                x = 0
                y = self.bands_y[out.n2]

        else:  # dump
            if x > 0 and f > 0:
                y_dest: uint256 = Inv / f - g
                if (y_dest - y) * fee / 10**18 >= in_amount_left:
                    # This is the last band
                    out.last_tick_j = Inv / (g + (y + in_amount_left * 10**18 / fee)) - f
                    y += in_amount_left
                    out.out_amount += unsafe_mul(unsafe_div(x - out.last_tick_j, BORROWED_PRECISION), BORROWED_PRECISION)
                    out.ticks_in[i] = y
                    out.in_amount = in_amount
                    return out

                else:
                    # We go into the next band
                    dy: uint256 = (y_dest - y) * fee / 10**18
                    in_amount_left -= dy
                    out.ticks_in[i] = y + dy
                    in_amount_used += dy
                    out.out_amount += x

            if i != MAX_TICKS - 1:
                if out.n2 == min_band:
                    break
                out.n2 -= 1
                p_o_up = p_o_up * A / unsafe_sub(A, 1)
                x = self.bands_x[out.n2]
                y = 0

    # Round up what goes in and down what goes out
    out.in_amount = in_amount_used + in_amount_afee
    if pump:
        in_amount_used = unsafe_mul(unsafe_div(in_amount_used, BORROWED_PRECISION), BORROWED_PRECISION)
        if in_amount_used != out.in_amount:
            out.in_amount = in_amount_used + BORROWED_PRECISION
        out.out_amount = unsafe_mul(unsafe_div(out.out_amount, collateral_precision), collateral_precision)
    else:
        in_amount_used = unsafe_mul(unsafe_div(in_amount_used, collateral_precision), collateral_precision)
        if in_amount_used != out.in_amount:
            out.in_amount = in_amount_used + collateral_precision
        out.out_amount = unsafe_mul(unsafe_div(out.out_amount, BORROWED_PRECISION), BORROWED_PRECISION)
    return out


@internal
@view
def _get_dxdy(i: uint256, j: uint256, in_amount: uint256) -> DetailedTrade:
    """
    Method to be used to figure if we have some in_amount left or not
    """
    assert (i == 0 and j == 1) or (i == 1 and j == 0), "Wrong index"
    collateral_precision: uint256 = self.collateral_precision
    out: DetailedTrade = empty(DetailedTrade)
    if in_amount == 0:
        return out
    in_precision: uint256 = collateral_precision
    out_precision: uint256 = BORROWED_PRECISION
    if i == 0:
        in_precision = BORROWED_PRECISION
        out_precision = collateral_precision
    out = self.calc_swap_out(i == 0, in_amount * in_precision, self.price_oracle_contract.price())
    out.in_amount = unsafe_div(out.in_amount, in_precision)
    out.out_amount = unsafe_div(out.out_amount, out_precision)
    return out


@external
@view
def get_dy(i: uint256, j: uint256, in_amount: uint256) -> uint256:
    return self._get_dxdy(i, j, in_amount).out_amount


@external
@view
def get_dxdy(i: uint256, j: uint256, in_amount: uint256) -> (uint256, uint256):
    """
    Method to be used to figure if we have some in_amount left or not
    """
    out: DetailedTrade = self._get_dxdy(i, j, in_amount)
    return (out.in_amount, out.out_amount)


# Unused
# @external
# @view
# def get_end_price(i: uint256, j: uint256, in_amount: uint256) -> uint256:
#     out: DetailedTrade = self._get_dxdy(i, j, in_amount)
#     x: uint256 = 0
#     y: uint256 = 0
#     if i == 0:  # pump
#         x = out.ticks_in[abs(out.n2 - out.n1)]
#         y = out.last_tick_j
#     else:  # dump
#         x = out.last_tick_j
#         y = out.ticks_in[abs(out.n2 - out.n1)]
#     return self._get_p(out.n2, x, y)


@external
@nonreentrant('lock')
def exchange(i: uint256, j: uint256, in_amount: uint256, min_amount: uint256, _for: address = msg.sender) -> uint256:
    assert (i == 0 and j == 1) or (i == 1 and j == 0), "Wrong index"
    if in_amount == 0:
        return 0

    in_coin: ERC20 = BORROWED_TOKEN
    out_coin: ERC20 = self.collateral_token
    in_precision: uint256 = BORROWED_PRECISION
    out_precision: uint256 = self.collateral_precision
    if i == 1:
        in_precision = out_precision
        in_coin = out_coin
        out_precision = BORROWED_PRECISION
        out_coin = BORROWED_TOKEN

    out: DetailedTrade = self.calc_swap_out(i == 0, in_amount * in_precision, self.price_oracle_contract.price_w())
    in_amount_done: uint256 = unsafe_div(out.in_amount, in_precision)
    out_amount_done: uint256 = unsafe_div(out.out_amount, out_precision)
    assert out_amount_done >= min_amount, "Slippage"
    if out_amount_done == 0:
        return 0

    in_coin.transferFrom(msg.sender, self, in_amount_done)
    out_coin.transfer(_for, out_amount_done)

    A: uint256 = self.A
    p_base_mul: uint256 = self.p_base_mul
    n: int256 = out.n1
    step: int256 = 1
    if out.n2 < out.n1:
        step = -1
    for k in range(MAX_TICKS):
        if i == 0:
            self.bands_x[n] = out.ticks_in[k]
            if n == out.n2:
                self.bands_y[n] = out.last_tick_j
                break
            self.bands_y[n] = 0

        else:
            self.bands_y[n] = out.ticks_in[k]
            if n == out.n2:
                self.bands_x[n] = out.last_tick_j
                break
            self.bands_x[n] = 0

        if step == 1:
            p_base_mul = unsafe_div(p_base_mul * unsafe_sub(A, 1), A)
        else:
            p_base_mul = p_base_mul * A / unsafe_sub(A, 1)
        n += step

    self.active_band = n
    self.p_base_mul = p_base_mul

    log TokenExchange(_for, i, in_amount_done, j, out_amount_done)

    return out_amount_done


@internal
@view
def get_xy_up(user: address, use_y: bool) -> uint256:
    """
    Measure the amount of y in the band n if we adiabatically trade near p_oracle on the way up
    """
    ns: int256[2] = self._read_user_tick_numbers(user)
    ticks: uint256[MAX_TICKS] = self._read_user_ticks(user, ns[1] - ns[0] + 1)
    if ticks[0] == 0:
        return 0
    p_o: uint256 = self.price_oracle_contract.price()

    n: int256 = ns[0] - 1
    n_active: int256 = self.active_band
    p_o_down: uint256 = self._p_oracle_band(n, True)
    XY: uint256 = 0
    A: uint256 = self.A
    sqrt_band_ratio: uint256 = self.sqrt_band_ratio

    for i in range(MAX_TICKS):
        n += 1
        if n > ns[1]:
            break
        p_o_up: uint256 = p_o_down
        p_o_down = unsafe_div(p_o_down * unsafe_sub(A, 1), A)
        p_current_mid: uint256 = p_o**2 / p_o_down * p_o / p_o_down * unsafe_sub(A, 1) / A
        total_share: uint256 = self.total_shares[n]
        user_share: uint256 = ticks[i]

        x: uint256 = 0
        y: uint256 = 0
        if n >= n_active:
            y = self.bands_y[n]
        if n <= n_active:
            x = self.bands_x[n]

        # if p_o > p_o_up - we "trade" everything to y and then convert to the result
        # if p_o < p_o_down - "trade" to x, then convert to result
        # otherwise we are in-band, so we do the more complex logic to trade
        # to p_o rather than to the edge of the band
        # trade to the edge of the band == getting to the band edge while p_o=const

        # Cases when special conversion is not needed (to save on computations)
        if x == 0 or y == 0:

            if x == 0 and y == 0:
                continue

            if p_o > p_o_up:  # p_o < p_current_down
                # all to y at constant p_o, then to target currency adiabatically
                y_equiv: uint256 = y
                if y == 0:
                    y_equiv = x * 10**18 / p_current_mid
                if use_y:
                    XY += y_equiv * user_share / total_share
                else:
                    XY += y_equiv * p_o_up / sqrt_band_ratio * user_share / total_share
                continue

            elif p_o < p_o_down:  # p_o > p_current_up
                # all to x at constant p_o, then to target currency adiabatically
                x_equiv: uint256 = x
                if x == 0:
                    x_equiv = y * p_current_mid / 10**18
                if use_y:
                    XY += x_equiv * sqrt_band_ratio / p_o_up * user_share / total_share
                else:
                    XY += x_equiv * user_share / total_share
                continue

        # If we are here - we need to "trade" to somewhere mid-band
        # So we need more heavy math

        y0: uint256 = self._get_y0(x, y, p_o, p_o_up, A)
        f: uint256 = A * y0 * p_o / p_o_up * p_o / 10**18
        g: uint256 = unsafe_sub(A, 1) * y0 * p_o_up / p_o
        # (f + x)(g + y) = const = p_top * A**2 * y0**2 = I
        Inv: uint256 = (f + x) * (g + y)
        # p = (f + x) / (g + y) => p * (g + y)**2 = I or (f + x)**2 / p = I

        # First, "trade" in this band to p_oracle
        y_o: uint256 = max(self.sqrt_int(Inv / p_o), g) - g
        x_o: uint256 = max(Inv / (g + y_o), f) - f

        # Adiabatic conversion of edge bands
        if x_o == 0:
            if use_y:
                XY += y * user_share / total_share
            else:
                XY += y * p_o_up / sqrt_band_ratio * user_share / total_share
            continue

        if y_o == 0:
            if use_y:
                XY += x * sqrt_band_ratio / p_o_up * user_share / total_share
            else:
                XY += x * user_share / total_share
            continue

        # Now adiabatic conversion from definitely in-band
        if use_y:
            XY += (y_o + x_o * 10**18 / self.sqrt_int(p_o_up * p_o / 10**18)) * user_share / total_share

        else:
            XY += (x_o + y_o * self.sqrt_int(p_o_down * p_o / 10**18) / 10**18) * user_share / total_share

    if use_y:
        return unsafe_div(XY, self.collateral_precision)
    else:
        return unsafe_div(XY, BORROWED_PRECISION)


@external
@view
def get_y_up(user: address) -> uint256:
    return self.get_xy_up(user, True)


@external
@view
def get_x_down(user: address) -> uint256:
    return self.get_xy_up(user, False)


@external
@view
def get_sum_xy(user: address) -> uint256[2]:
    x: uint256 = 0
    y: uint256 = 0
    ns: int256[2] = self._read_user_tick_numbers(user)
    ticks: uint256[MAX_TICKS] = self._read_user_ticks(user, ns[1] - ns[0] + 1)
    for i in range(MAX_TICKS):
        total_shares: uint256 = self.total_shares[ns[0]]
        x += self.bands_x[ns[0]] * ticks[i] / total_shares
        y += self.bands_y[ns[0]] * ticks[i] / total_shares
        if ns[0] == ns[1]:
            break
        ns[0] += 1
    return [unsafe_div(x, BORROWED_PRECISION), unsafe_div(y, self.collateral_precision)]


@external
@view
def get_amount_for_price(p: uint256) -> (uint256, bool):
    """
    Amount necessary to be exchange to have the AMM at the final price p
    :returns: amount, is_pump
    """
    n: int256 = self.active_band
    A: uint256 = self.A
    Aneg1: uint256 = unsafe_sub(A, 1)
    A2: uint256 = pow_mod256(A, 2)
    Aneg12: uint256 = pow_mod256(Aneg1, 2)
    x: uint256 = self.bands_x[n]
    y: uint256 = self.bands_y[n]
    p_up: uint256 = self._p_current_band(n, True)  # p_current_up
    p_down: uint256 = unsafe_div(p_up * Aneg12, A2)     # p_current_down
    p_o_up: uint256 = unsafe_div(self._base_price() * self.p_base_mul, 10**18)
    p_o: uint256 = self.price_oracle_contract.price()
    pump: bool = True
    if p < self._get_p(n, x, y):
        pump = False
    amount: uint256 = 0
    y0: uint256 = 0
    f: uint256 = 0
    g: uint256 = 0
    Inv: uint256 = 0

    for i in range(100):
        not_empty: bool = x > 0 or y > 0
        if not_empty:
            y0 = self._get_y0(x, y, p_o, p_o_up, A)
            f = unsafe_div(A * y0 * p_o / p_o_up * p_o, 10**18)
            g = unsafe_div(Aneg1 * y0 * p_o_up, p_o)
            Inv = (f + x) * (g + y)

        if p <= p_up and p >= p_down:
            if not_empty:
                ynew: uint256 = unsafe_sub(max(self.sqrt_int(Inv / p), g), g)
                xnew: uint256 = unsafe_sub(max(Inv / (g + ynew), f), f)
                if pump:
                    amount += xnew - x
                else:
                    amount += ynew - y
            break

        if pump:
            if not_empty:
                amount += (Inv / g - f) - x
            n += 1
            p_down = p_up
            p_up = unsafe_div(p_up * A2, Aneg12)
            p_o_up = unsafe_div(p_o_up * Aneg1, A)

        else:
            if not_empty:
                amount += (Inv / f - g) - y
            n -= 1
            p_up = p_down
            p_down = unsafe_div(p_down * Aneg12, A2)
            p_o_up = unsafe_div(p_o_up * A, Aneg1)

        x = self.bands_x[n]
        y = self.bands_y[n]

    amount = amount * 10**18 / unsafe_sub(10**18, self.fee)
    if amount == 0:
        return 0, pump

    # Precision and round up
    if pump:
        amount = unsafe_add(unsafe_div(unsafe_sub(amount, 1), BORROWED_PRECISION), 1)
    else:
        amount = unsafe_add(unsafe_div(unsafe_sub(amount, 1), self.collateral_precision), 1)

    return amount, pump


@external
def set_rate(rate: int256) -> uint256:
    assert msg.sender == self.admin
    rate_mul: uint256 = self._rate_mul()
    self.rate_mul = rate_mul
    self.rate_time = block.timestamp
    self.rate = rate
    log SetRate(rate, rate_mul, block.timestamp)
    return rate_mul


@external
def set_fee(fee: uint256):
    assert msg.sender == self.admin
    assert fee < 10**18, "Fee is too high"
    self.fee = fee
    log SetFee(fee)
