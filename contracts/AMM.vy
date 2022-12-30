# @version 0.3.7

# Glossary of variables and terms
# =======================
# * ticks, bands - price ranges where liquidity is deposited
# * x - coin which is being borrowed, typically stablecoin
# * y - collateral coin (for example, wETH)
# * A - amplification, the measure of how concentrated the tick is
# * rate - interest rate
# * rate_mul - rate multiplier, 1 + integral(rate * dt)
# * active_band - current band. Other bands are either in one or other coin, but not both
# * min_band - bands below this are definitely empty
# * max_band - bands above this are definitely empty
# * bands_x[n], bands_y[n] - amounts of coin x or y deposited in band n
# * user_shares[user,n] / total_shares[n] - fraction of n'th band owned by a user
# * p_oracle - external oracle price (can be from another AMM)
# * p (as in get_p) - current price of AMM. It depends not only on the balances (x,y) in the band and active_band, but
# also on p_oracle
# * p_current_up, p_current_down - the value of p at constant p_oracle when y=0 or x=0 respectively for the band n
# * p_oracle_up, p_oracle_down - edges of the band when p=p_oracle (steady state), happen when x=0 or y=0 respectively,
# for band n.
# * Grid of bands is set for p_oracle values such as:
#   * p_oracle_up(n) = base_price * ((A - 1) / A)**n
#   * p_oracle_down(n) = p_oracle_up(n) * (A - 1) / A = p_oracle_up(n+1)
# * p_current_up and p_oracle_up change in opposite directions with n
# * When intereste is accrued - all the grid moves by change of base_price
#
# Bonding curve reads as:
# (f + x) * (g + y) = Inv = p_oracle * A**2 * y0**2
# =======================

interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def approve(_spender: address, _value: uint256) -> bool: nonpayable

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

interface LMGauge:
    def callback_collateral_shares(n: int256, collateral_per_share: DynArray[uint256, MAX_TICKS_UINT]): nonpayable
    def callback_user_shares(n: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT]): nonpayable


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
    amount_borrowed: uint256
    amount_collateral: uint256

event SetRate:
    rate: uint256
    rate_mul: uint256
    time: uint256

event SetFee:
    fee: uint256

event SetAdminFee:
    fee: uint256

event SetPriceOracle:
    price_oracle: address


MAX_TICKS: constant(int256) = 50
MAX_TICKS_UINT: constant(uint256) = 50
MAX_SKIP_TICKS: constant(int256) = 1024


struct UserTicks:
    ns: int256  # packs n1 and n2, each is int128
    ticks: uint256[MAX_TICKS/2]  # Share fractions packed 2 per slot

struct DetailedTrade:
    in_amount: uint256
    out_amount: uint256
    n1: int256
    n2: int256
    ticks_in: DynArray[uint256, MAX_TICKS_UINT]
    last_tick_j: uint256
    admin_fee: uint256


BORROWED_TOKEN: immutable(ERC20)    # x
BORROWED_PRECISION: immutable(uint256)
COLLATERAL_TOKEN: immutable(ERC20)  # y
COLLATERAL_PRECISION: immutable(uint256)
BASE_PRICE: immutable(uint256)
admin: public(address)

A: public(immutable(uint256))
Aminus1: immutable(uint256)
A2: immutable(uint256)
Aminus12: immutable(uint256)
SQRT_BAND_RATIO: immutable(uint256)  # sqrt(A / (A - 1))
LOG_A_RATIO: immutable(int256)  # ln(A / (A - 1))

fee: public(uint256)
admin_fee: public(uint256)
rate: public(uint256)
rate_time: uint256
rate_mul: uint256
active_band: public(int256)
min_band: public(int256)
max_band: public(int256)

admin_fees_x: public(uint256)
admin_fees_y: public(uint256)

price_oracle_contract: public(PriceOracle)

bands_x: public(HashMap[int256, uint256])
bands_y: public(HashMap[int256, uint256])

total_shares: HashMap[int256, uint256]
user_shares: HashMap[address, UserTicks]

liquidity_mining_callback: public(LMGauge)


@external
def __init__(
        _borrowed_token: address,
        _borrowed_precision: uint256,
        _collateral_token: address,
        _collateral_precision: uint256,
        _A: uint256,
        _sqrt_band_ratio: uint256,
        _log_A_ratio: int256,
        _base_price: uint256,
        fee: uint256,
        admin_fee: uint256,
        _price_oracle_contract: address,
    ):
    """
    @notice LLAMMA constructor
    @param _borrowed_token Token which is being borrowed
    @param _collateral_token Token used as collateral
    @param _collateral_precision Precision of collateral: we pass it because we want the blueprint to fit into bytecode
    @param _A "Amplification coefficient" which also defines density of liquidity and band size. Relative band size is 1/_A
    @param _sqrt_band_ratio Precomputed int(sqrt(A / (A - 1)) * 1e18)
    @param _log_A_ratio Precomputed int(ln(A / (A - 1)) * 1e18)
    @param _base_price Typically the initial crypto price at which AMM is deployed. Will correspond to band 0
    @param fee Relative fee of the AMM: int(fee * 1e18)
    @param admin_fee Admin fee: how much of fee goes to admin. 50% === int(0.5 * 1e18)
    @param _price_oracle_contract External price oracle which has price() and price_w() methods
           which both return current price of collateral multiplied by 1e18
    """
    BORROWED_TOKEN = ERC20(_borrowed_token)
    BORROWED_PRECISION = _borrowed_precision
    COLLATERAL_TOKEN = ERC20(_collateral_token)
    COLLATERAL_PRECISION = _collateral_precision
    A = _A
    BASE_PRICE = _base_price

    Aminus1 = unsafe_sub(A, 1)
    A2 = pow_mod256(A, 2)
    Aminus12 = pow_mod256(unsafe_sub(A, 1), 2)

    self.fee = fee
    self.admin_fee = admin_fee
    self.price_oracle_contract = PriceOracle(_price_oracle_contract)

    self.rate_mul = 10**18

    # sqrt(A / (A - 1)) - needs to be pre-calculated externally
    SQRT_BAND_RATIO = _sqrt_band_ratio
    # log(A / (A - 1)) - needs to be pre-calculated externally
    LOG_A_RATIO = _log_A_ratio


@internal
def approve_max(token: ERC20, _admin: address):
    """
    Approve max in a separate function because it uses less bytespace than
    calling directly, and gas doesn't matter in set_admin
    """
    assert token.approve(_admin, max_value(uint256), default_return_value=True)


@external
def set_admin(_admin: address):
    """
    @notice Set admin of the AMM. Typically it's a controller (unless it's tests)
    @param _admin Admin address
    """
    assert self.admin == empty(address)
    self.admin = _admin
    self.approve_max(BORROWED_TOKEN, _admin)
    self.approve_max(COLLATERAL_TOKEN, _admin)


@internal
@pure
def sqrt_int(_x: uint256) -> uint256:
    """
    @notice Wrapping isqrt builtin because otherwise it will be repeated every time instead of calling
    @param _x Square root's input in "normal" units, e.g. sqrt_int(1) == 1
    """
    return isqrt(_x)


@external
@pure
def coins(i: uint256) -> address:
    return [BORROWED_TOKEN.address, COLLATERAL_TOKEN.address][i]


@external
@view
def price_oracle() -> uint256:
    """
    @notice Value returned by the external price oracle contract
    """
    return self.price_oracle_contract.price()


@internal
@view
def _rate_mul() -> uint256:
    """
    @notice Rate multiplier which is 1.0 + integral(rate, dt)
    @return Rate multiplier in units where 1.0 == 1e18
    """
    return self.rate_mul + self.rate * (block.timestamp - self.rate_time)


@external
@view
def get_rate_mul() -> uint256:
    """
    @notice Rate multiplier which is 1.0 + integral(rate, dt)
    @return Rate multiplier in units where 1.0 == 1e18
    """
    return self._rate_mul()


@internal
@view
def _base_price() -> uint256:
    """
    @notice Price which corresponds to band 0.
            Base price grows with time to account for interest rate (which is 0 by default)
    """
    return unsafe_div(BASE_PRICE * self._rate_mul(), 10**18)


@external
@view
def get_base_price() -> uint256:
    """
    @notice Price which corresponds to band 0.
            Base price grows with time to account for interest rate (which is 0 by default)
    """
    return self._base_price()


@internal
@view
def _p_oracle_up(n: int256) -> uint256:
    """
    @notice Upper oracle price for the band to have liquidity when p = p_oracle
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    # p_oracle_up(n) = p_base * ((A - 1) / A) ** n
    # p_oracle_down(n) = p_base * ((A - 1) / A) ** (n + 1) = p_oracle_up(n+1)
    # return unsafe_div(self._base_price() * self.exp_int(-n * LOG_A_RATIO), 10**18)

    power: int256 = -n * LOG_A_RATIO
    # exp(-n * LOG_A_RATIO)
    ## Exp implementation based on solmate's
    assert power > -42139678854452767551
    assert power < 135305999368893231589

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

    exp_result: uint256 = shift(
        unsafe_mul(convert(unsafe_div(p, q), uint256), 3822833074963236453042738258902158003155416615667),
        unsafe_sub(k, 195))
    ## End exp
    return unsafe_div(self._base_price() * exp_result, 10**18)


@internal
@view
def _p_current_band(n: int256) -> uint256:
    """
    @notice Lowest possible price of the band at current oracle price
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    # k = (self.A - 1) / self.A  # equal to (p_down / p_up)
    # p_base = self.p_base * k ** n = p_oracle_up(n)
    p_base: uint256 = self._p_oracle_up(n)

    # return self.p_oracle**3 / p_base**2
    p_oracle: uint256 = self.price_oracle_contract.price()
    return unsafe_div(p_oracle**2 / p_base * p_oracle, p_base)


@external
@view
def p_current_up(n: int256) -> uint256:
    """
    @notice Highest possible price of the band at current oracle price
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    return self._p_current_band(n + 1)


@external
@view
def p_current_down(n: int256) -> uint256:
    """
    @notice Lowest possible price of the band at current oracle price
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    return self._p_current_band(n)


@external
@view
def p_oracle_up(n: int256) -> uint256:
    """
    @notice Highest oracle price for the band to have liquidity when p = p_oracle
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    return self._p_oracle_up(n)


@external
@view
def p_oracle_down(n: int256) -> uint256:
    """
    @notice Lowest oracle price for the band to have liquidity when p = p_oracle
    @param n Band number (can be negative)
    @return Price at 1e18 base
    """
    return self._p_oracle_up(n + 1)


@internal
@view
def _get_y0(x: uint256, y: uint256, p_o: uint256, p_o_up: uint256) -> uint256:
    """
    @notice Calculate y0 for the invariant based on current liquidity in band.
            The value of y0 has a meaning of amount of collateral when band has no stablecoin
            but current price is equal to both oracle price and upper band price.
    @param x Amount of stablecoin in band
    @param y Amount of collateral in band
    @param p_o External oracle price
    @param p_o_up Upper boundary of the band
    @return y0
    """
    assert p_o != 0
    # solve:
    # p_o * A * y0**2 - y0 * (p_oracle_up/p_o * (A-1) * x + p_o**2/p_oracle_up * A * y) - xy = 0
    b: uint256 = 0
    # p_o_up * unsafe_sub(A, 1) * x / p_o + A * p_o**2 / p_o_up * y / 10**18
    if x != 0:
        b = unsafe_div(p_o_up * Aminus1 * x, p_o)
    if y != 0:
        b += unsafe_div(A * p_o**2 / p_o_up * y, 10**18)
    if x > 0 and y > 0:
        D: uint256 = b**2 + unsafe_div(((4 * A) * p_o) * y, 10**18) * x
        return unsafe_div((b + self.sqrt_int(D)) * 10**18, unsafe_mul(2 * A, p_o))
    else:
        return unsafe_div(b * 10**18, A * p_o)


@external
@view
def get_y0(_n: int256) -> uint256:
    """
    @notice Calculate y0 for the invariant based on current liquidity in band.
            Unlike the internal method, this one reads most of the inputs from the state
    @param _n Band number
    @return y0
    """
    n: int256 = _n
    return self._get_y0(
        self.bands_x[n],
        self.bands_y[n],
        self.price_oracle_contract.price(),
        self._p_oracle_up(n)
    )


@internal
@view
def _get_p(n: int256, x: uint256, y: uint256) -> uint256:
    """
    @notice Get current AMM price in band
    @param n Band number
    @param x Amount of stablecoin in band
    @param y Amount of collateral in band
    @return Current price at 1e18 base
    """
    p_o_up: uint256 = self._p_oracle_up(n)
    p_o: uint256 = self.price_oracle_contract.price()

    # Special cases
    if x == 0:
        if y == 0:  # x and y are 0
            # Return mid-band
            return unsafe_div((unsafe_div(p_o**2 / p_o_up * p_o, p_o_up) * A), Aminus1)
        # if x == 0: # Lowest point of this band -> p_current_down
        return unsafe_div(p_o**2 / p_o_up * p_o, p_o_up)
    if y == 0: # Highest point of this band -> p_current_up
        p_o_up = unsafe_div(p_o_up * Aminus1, A)  # now this is _actually_ p_o_down
        return unsafe_div(p_o**2 / p_o_up * p_o, p_o_up)

    y0: uint256 = self._get_y0(x, y, p_o, p_o_up)
    # ^ that call also checks that p_o != 0

    # (f(y0) + x) / (g(y0) + y)
    f: uint256 = A * y0 * p_o / p_o_up * p_o
    g: uint256 = unsafe_div(Aminus1 * y0 * p_o_up, p_o)
    return (f + x * 10**18) / (g + y)


@external
@view
@nonreentrant('lock')
def get_p() -> uint256:
    """
    @notice Get current AMM price in active_band
    @return Current price at 1e18 base
    """
    n: int256 = self.active_band
    return self._get_p(n, self.bands_x[n], self.bands_y[n])


@internal
@view
def _read_user_tick_numbers(user: address) -> int256[2]:
    """
    @notice Unpacks and reads user tick numbers
    @param user User address
    @return Lowest and highest band the user deposited into
    """
    ns: int256 = self.user_shares[user].ns
    n2: int256 = unsafe_div(ns, 2**128)
    n1: int256 = ns % 2**128
    if n1 >= 2**127:
        n1 = unsafe_sub(n1, 2**128)
        n2 = unsafe_add(n2, 1)
    return [n1, n2]


@external
@view
@nonreentrant('lock')
def read_user_tick_numbers(user: address) -> int256[2]:
    """
    @notice Unpacks and reads user tick numbers
    @param user User address
    @return Lowest and highest band the user deposited into
    """
    return self._read_user_tick_numbers(user)


@internal
@view
def _read_user_ticks(user: address, ns: int256[2]) -> DynArray[uint256, MAX_TICKS_UINT]:
    """
    @notice Unpacks and reads user ticks (shares) for all the ticks user deposited into
    @param user User address
    @param size Number of ticks the user deposited into
    @return Array of shares the user has
    """
    ticks: DynArray[uint256, MAX_TICKS_UINT] = []
    size: uint256 = convert(ns[1] - ns[0] + 1, uint256)
    for i in range(MAX_TICKS / 2):
        if len(ticks) == size:
            break
        tick: uint256 = self.user_shares[user].ticks[i]
        ticks.append(tick & (2**128 - 1))
        if len(ticks) == size:
            break
        ticks.append(shift(tick, -128))
    return ticks


@external
@view
@nonreentrant('lock')
def can_skip_bands(n_end: int256) -> bool:
    """
    @notice Check that we have no liquidity between active_band and `n_end`
    """
    n: int256 = self.active_band
    for i in range(MAX_SKIP_TICKS):
        if n_end > n:
            if self.bands_y[n] != 0:
                return False
            n = unsafe_add(n, 1)
        else:
            if self.bands_x[n] != 0:
                return False
            n = unsafe_sub(n, 1)
        if n == n_end:  # not including n_end
            break
    return True
    # Actually skipping bands:
    # * change self.active_band to the new n
    # * change self.p_base_mul
    # to do n2-n1 times (if n2 > n1):
    # out.base_mul = unsafe_div(out.base_mul * Aminus1, A)


@external
@view
@nonreentrant('lock')
def active_band_with_skip() -> int256:
    n: int256 = self.active_band
    for i in range(MAX_SKIP_TICKS):
        if self.bands_x[n] != 0:
            break
        n -= 1
    return n


@external
@view
@nonreentrant('lock')
def has_liquidity(user: address) -> bool:
    """
    @notice Check if `user` has any liquidity in the AMM
    """
    return self.user_shares[user].ticks[0] != 0


@external
@nonreentrant('lock')
def deposit_range(user: address, amount: uint256, n1: int256, n2: int256, move_coins: bool):
    """
    @notice Deposit for a user in a range of bands. Only admin contract (Controller) can do it
    @param user User address
    @param amount Amount of collateral to deposit
    @param n1 Lower band in the deposit range
    @param n2 Upper band in the deposit range
    @param move_coins Should we actually execute transferFrom, or should we not do anything (because the Controller will do)
    """
    assert msg.sender == self.admin

    user_shares: DynArray[uint256, MAX_TICKS_UINT] = []

    n0: int256 = self.active_band

    # We assume that n1,n2 area already sorted (and they are in Controller)
    assert n2 < 2**127
    assert n1 > -2**127

    # Autoskip bands if we can
    for i in range(MAX_SKIP_TICKS + 1):
        if n1 > n0:
            if i != 0:
                self.active_band = n0
            break
        assert self.bands_x[n0] == 0 and i < MAX_SKIP_TICKS, "Deposit below current band"
        n0 -= 1

    if move_coins:
        assert COLLATERAL_TOKEN.transferFrom(user, self, amount, default_return_value=True)

    n_bands: uint256 = unsafe_add(convert(unsafe_sub(n2, n1), uint256), 1)
    assert n_bands <= MAX_TICKS_UINT

    y_per_band: uint256 = unsafe_div(amount * COLLATERAL_PRECISION, n_bands)
    assert y_per_band > 100, "Amount too low"

    save_n: bool = True
    if self.user_shares[user].ticks[0] != 0:  # Has liquidity
        ns: int256[2] = self._read_user_tick_numbers(user)
        assert ns[0] == n1 and ns[1] == n2, "Wrong range"
        save_n = False

    for i in range(MAX_TICKS):
        band: int256 = unsafe_add(n1, i)
        if band > n2:
            break

        assert self.bands_x[band] == 0, "Band not empty"
        y: uint256 = y_per_band
        if i == 0:
            y = amount * COLLATERAL_PRECISION - y * unsafe_sub(n_bands, 1)

        total_y: uint256 = self.bands_y[band]
        self.bands_y[band] = total_y + y

        # Total / user share
        s: uint256 = self.total_shares[band]
        ds: uint256 = y
        if s == 0:
            assert y < 2**128
        else:
            ds = s * y / total_y
            assert ds > 0, "Amount too low"
        user_shares.append(ds)
        s += ds
        self.total_shares[band] = s

    self.min_band = min(self.min_band, n1)
    self.max_band = max(self.max_band, n2)

    if save_n:
        self.user_shares[user].ns = n1 + n2 * 2**128

    ptr: uint256 = 0
    for j in range(MAX_TICKS_UINT / 2):
        if ptr >= n_bands:
            break
        tick: uint256 = user_shares[ptr]
        ptr = unsafe_add(ptr, 1)
        if n_bands != ptr:
            tick = tick | shift(user_shares[ptr], 128)
        ptr = unsafe_add(ptr, 1)
        self.user_shares[user].ticks[j] = tick

    self.rate_mul = self._rate_mul()
    self.rate_time = block.timestamp

    log Deposit(user, amount, n1, n2)


@external
@nonreentrant('lock')
def withdraw(user: address) -> uint256[2]:
    """
    @notice Withdraw all liquidity for the user. Only admin contract can do it
    @param user User who owns liquidity
    @return Amount of [stablecoins, collateral] withdrawn
    """
    assert msg.sender == self.admin

    ns: int256[2] = self._read_user_tick_numbers(user)
    user_shares: DynArray[uint256, MAX_TICKS_UINT] = self._read_user_ticks(user, ns)
    assert user_shares[0] > 0, "No deposits"

    total_x: uint256 = 0
    total_y: uint256 = 0
    min_band: int256 = self.min_band
    old_min_band: int256 = min_band
    max_band: int256 = self.max_band
    old_max_band: int256 = max_band

    for i in range(MAX_TICKS):
        x: uint256 = self.bands_x[ns[0]]
        y: uint256 = self.bands_y[ns[0]]
        ds: uint256 = user_shares[i]
        s: uint256 = self.total_shares[ns[0]]
        dx: uint256 = x * ds / s
        dy: uint256 = unsafe_div(y * ds, s)

        self.total_shares[ns[0]] = s - ds
        x -= dx
        y -= dy
        if ns[0] == min_band:
            if x == 0:
                if y == 0:
                    min_band += 1
        if x > 0 or y > 0:
            max_band = ns[0]
        self.bands_x[ns[0]] = x
        self.bands_y[ns[0]] = y
        total_x += dx
        total_y += dy

        if ns[0] == ns[1]:
            break
        else:
            ns[0] = unsafe_add(ns[0], 1)

    # Empty the ticks
    self.user_shares[user].ticks[0] = 0

    if old_min_band != min_band:
        self.min_band = min_band
    if old_max_band <= ns[1]:
        self.max_band = max_band

    total_x = unsafe_div(total_x, BORROWED_PRECISION)
    total_y = unsafe_div(total_y, COLLATERAL_PRECISION)
    log Withdraw(user, total_x, total_y)

    self.rate_mul = self._rate_mul()
    self.rate_time = block.timestamp

    return [total_x, total_y]


@internal
@view
def calc_swap_out(pump: bool, in_amount: uint256, p_o: uint256) -> DetailedTrade:
    """
    @notice Calculate the amount which can be obtained as a result of exchange.
            If couldn't exchange all - will also update the amount which was actually used.
            Also returns other parameters related to state after swap.
            This function is core to the AMM functionality.
    @param pump Indicates whether the trade buys or sells collateral
    @param in_amount Amount of token going in
    @param p_o Current oracle price
    @return Amounts spent and given out, initial and final bands of the AMM, new
            amounts of coins in bands in the AMM, as well as admin fee charged,
            all in one data structure
    """
    # pump = True: borrowable (USD) in, collateral (ETH) out; going up
    # pump = False: collateral (ETH) in, borrowable (USD) out; going down
    min_band: int256 = self.min_band
    max_band: int256 = self.max_band
    out: DetailedTrade = empty(DetailedTrade)
    out.n2 = self.active_band
    p_o_up: uint256 = self._p_oracle_up(out.n2)
    x: uint256 = self.bands_x[out.n2]
    y: uint256 = self.bands_y[out.n2]

    in_amount_left: uint256 = in_amount
    antifee: uint256 = unsafe_div((10**18)**2, unsafe_sub(10**18, self.fee))
    admin_fee: uint256 = self.admin_fee
    j: uint256 = MAX_TICKS_UINT

    for i in range(MAX_TICKS + MAX_SKIP_TICKS):
        y0: uint256 = 0
        f: uint256 = 0
        g: uint256 = 0
        Inv: uint256 = 0

        if x > 0 or y > 0:
            if j == MAX_TICKS_UINT:
                out.n1 = out.n2
                j = 0
            y0 = self._get_y0(x, y, p_o, p_o_up)  # <- also checks p_o
            f = unsafe_div(A * y0 * p_o / p_o_up * p_o, 10**18)
            g = unsafe_div(Aminus1 * y0 * p_o_up, p_o)
            Inv = (f + x) * (g + y)

        if j != MAX_TICKS_UINT:
            # Initialize to zero in case we have 0 bands between full bands
            out.ticks_in.append(0)

        if pump:
            if y != 0:
                if g != 0:
                    x_dest: uint256 = (unsafe_div(Inv, g) - f) - x
                    dx: uint256 = unsafe_div(x_dest * antifee, 10**18)
                    if dx >= in_amount_left:
                        # This is the last band
                        x_dest = unsafe_div(in_amount_left * 10**18, antifee)  # LESS than in_amount_left
                        out.last_tick_j = Inv / (f + (x + x_dest)) - g  # Should be always >= 0
                        x_dest = unsafe_div(unsafe_sub(in_amount_left, x_dest) * admin_fee, 10**18)  # abs admin fee now
                        x += in_amount_left  # x is precise after this
                        # Round down the output
                        out.out_amount += y - out.last_tick_j
                        out.ticks_in[j] = x - x_dest
                        out.in_amount = in_amount
                        out.admin_fee = unsafe_add(out.admin_fee, x_dest)
                        break

                    else:
                        # We go into the next band
                        x_dest = unsafe_div(unsafe_sub(dx, x_dest) * admin_fee, 10**18)  # abs admin fee now
                        in_amount_left -= dx
                        out.ticks_in[j] = x + dx - x_dest
                        out.in_amount += dx
                        out.out_amount += y
                        out.admin_fee = unsafe_add(out.admin_fee, x_dest)

            if i != MAX_TICKS + MAX_SKIP_TICKS - 1:
                if out.n2 == max_band:
                    break
                if j == MAX_TICKS_UINT - 1:
                    break
                out.n2 += 1
                p_o_up = unsafe_div(p_o_up * Aminus1, A)
                x = 0
                y = self.bands_y[out.n2]

        else:  # dump
            if x != 0:
                if f != 0:
                    y_dest: uint256 = (unsafe_div(Inv, f) - g) - y
                    dy: uint256 = unsafe_div(y_dest * antifee, 10**18)
                    if dy >= in_amount_left:
                        # This is the last band
                        y_dest = unsafe_div(in_amount_left * 10**18, antifee)
                        out.last_tick_j = Inv / (g + (y + y_dest)) - f
                        y_dest = unsafe_div(unsafe_sub(in_amount_left, y_dest) * admin_fee, 10**18)  # abs admin fee now
                        y += in_amount_left
                        out.out_amount += x - out.last_tick_j
                        out.ticks_in[j] = y - y_dest
                        out.in_amount = in_amount
                        out.admin_fee = unsafe_add(out.admin_fee, y_dest)
                        break

                    else:
                        # We go into the next band
                        y_dest = unsafe_div(unsafe_sub(dy, y_dest) * admin_fee, 10**18)  # abs admin fee now
                        in_amount_left -= dy
                        out.ticks_in[j] = y + dy - y_dest
                        out.in_amount += dy
                        out.out_amount += x
                        out.admin_fee = unsafe_add(out.admin_fee, y_dest)

            if i != MAX_TICKS + MAX_SKIP_TICKS - 1:
                if out.n2 == min_band:
                    break
                if j == MAX_TICKS_UINT - 1:
                    break
                out.n2 -= 1
                p_o_up = unsafe_div(p_o_up * A, Aminus1)
                x = self.bands_x[out.n2]
                y = 0

        if j != MAX_TICKS_UINT:
            j = unsafe_add(j, 1)

    # Round up what goes in and down what goes out
    in_precision: uint256 = COLLATERAL_PRECISION
    out_precision: uint256 = BORROWED_PRECISION
    if pump:
        in_precision = BORROWED_PRECISION
        out_precision = COLLATERAL_PRECISION
    # ceil(in_amount_used/BORROWED_PRECISION) * BORROWED_PRECISION
    out.in_amount = unsafe_mul(unsafe_div(unsafe_add(out.in_amount, unsafe_sub(in_precision, 1)), in_precision), in_precision)
    out.out_amount = unsafe_mul(unsafe_div(out.out_amount, out_precision), out_precision)

    # If out_amount is zeroed because of rounding off - don't charge admin fees
    if out.out_amount == 0:
        out.admin_fee = 0

    return out


@internal
@view
def _get_dxdy(i: uint256, j: uint256, in_amount: uint256) -> DetailedTrade:
    """
    @notice Method to use to calculate out amount and spent in amount
    @param i Input coin index
    @param j Output coin index
    @param in_amount Amount of input coin to swap
    @return DetailedTrade with all swap results
    """
    assert (i == 0 and j == 1) or (i == 1 and j == 0), "Wrong index"
    out: DetailedTrade = empty(DetailedTrade)
    if in_amount == 0:
        return out
    in_precision: uint256 = COLLATERAL_PRECISION
    out_precision: uint256 = BORROWED_PRECISION
    if i == 0:
        in_precision = BORROWED_PRECISION
        out_precision = COLLATERAL_PRECISION
    out = self.calc_swap_out(i == 0, in_amount * in_precision, self.price_oracle_contract.price())
    out.in_amount = unsafe_div(out.in_amount, in_precision)
    out.out_amount = unsafe_div(out.out_amount, out_precision)
    return out


@external
@view
@nonreentrant('lock')
def get_dy(i: uint256, j: uint256, in_amount: uint256) -> uint256:
    """
    @notice Method to use to calculate out amount
    @param i Input coin index
    @param j Output coin index
    @param in_amount Amount of input coin to swap
    @return Amount of coin j to give out
    """
    return self._get_dxdy(i, j, in_amount).out_amount


@external
@view
@nonreentrant('lock')
def get_dxdy(i: uint256, j: uint256, in_amount: uint256) -> (uint256, uint256):
    """
    @notice Method to use to calculate out amount and spent in amount
    @param i Input coin index
    @param j Output coin index
    @param in_amount Amount of input coin to swap
    @return A tuple with in_amount used and out_amount returned
    """
    out: DetailedTrade = self._get_dxdy(i, j, in_amount)
    return (out.in_amount, out.out_amount)


@external
@nonreentrant('lock')
def exchange(i: uint256, j: uint256, in_amount: uint256, min_amount: uint256, _for: address = msg.sender) -> uint256:
    """
    @notice Exchanges two coins, callable by anyone
    @param i Input coin index
    @param j Output coin index
    @param in_amount Amount of input coin to swap
    @param min_amount Minimal amount to get as output (revert if less)
    @param _for Address to send coins to
    @return Amount of coins given out
    """
    assert (i == 0 and j == 1) or (i == 1 and j == 0), "Wrong index"
    if in_amount == 0:
        return 0

    in_coin: ERC20 = BORROWED_TOKEN
    out_coin: ERC20 = COLLATERAL_TOKEN
    in_precision: uint256 = BORROWED_PRECISION
    out_precision: uint256 = COLLATERAL_PRECISION
    if i == 1:
        in_precision = out_precision
        in_coin = out_coin
        out_precision = BORROWED_PRECISION
        out_coin = BORROWED_TOKEN

    out: DetailedTrade = self.calc_swap_out(i == 0, in_amount * in_precision, self.price_oracle_contract.price_w())
    out.admin_fee = unsafe_div(out.admin_fee, in_precision)
    if i == 0:
        self.admin_fees_x += out.admin_fee
    else:
        self.admin_fees_y += out.admin_fee
    in_amount_done: uint256 = unsafe_div(out.in_amount, in_precision)
    out_amount_done: uint256 = unsafe_div(out.out_amount, out_precision)
    assert out_amount_done >= min_amount, "Slippage"
    if out_amount_done == 0:
        return 0

    assert in_coin.transferFrom(msg.sender, self, in_amount_done, default_return_value=True)
    assert out_coin.transfer(_for, out_amount_done, default_return_value=True)

    n: int256 = out.n1

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

        if out.n2 < out.n1:
            n = unsafe_sub(n, 1)
        else:
            n = unsafe_add(n, 1)

    self.active_band = n

    log TokenExchange(_for, i, in_amount_done, j, out_amount_done)

    return out_amount_done


@internal
@view
def get_xy_up(user: address, use_y: bool) -> uint256:
    """
    @notice Measure the amount of y (collateral) in the band n if we adiabatically trade near p_oracle on the way up,
            or the amount of x (stablecoin) if we trade adiabatically down
    @param user User the amount is calculated for
    @param use_y Calculate amount of collateral if True and of stablecoin if False
    @return Amount of coins
    """
    ns: int256[2] = self._read_user_tick_numbers(user)
    ticks: DynArray[uint256, MAX_TICKS_UINT] = self._read_user_ticks(user, ns)
    if ticks[0] == 0:
        return 0
    p_o: uint256 = self.price_oracle_contract.price()
    assert p_o != 0

    n: int256 = ns[0] - 1
    n_active: int256 = self.active_band
    p_o_down: uint256 = self._p_oracle_up(ns[0])
    XY: uint256 = 0

    for i in range(MAX_TICKS):
        n += 1
        if n > ns[1]:
            break
        x: uint256 = 0
        y: uint256 = 0
        if n >= n_active:
            y = self.bands_y[n]
        if n <= n_active:
            x = self.bands_x[n]
        # p_o_up: uint256 = self._p_oracle_up(n)
        p_o_up: uint256 = p_o_down
        # p_o_down = self._p_oracle_up(n + 1)
        p_o_down = unsafe_div(p_o_down * Aminus1, A)
        if x == 0:
            if y == 0:
                continue

        total_share: uint256 = self.total_shares[n]
        user_share: uint256 = ticks[i]
        if total_share == 0:
            continue
        if user_share == 0:
            continue

        # Also this will revert if p_o_down is 0, and p_o_down is 0 if p_o_up is 0
        p_current_mid: uint256 = unsafe_div(unsafe_div(p_o**2 / p_o_down * p_o, p_o_down) * Aminus1, A)

        # if p_o > p_o_up - we "trade" everything to y and then convert to the result
        # if p_o < p_o_down - "trade" to x, then convert to result
        # otherwise we are in-band, so we do the more complex logic to trade
        # to p_o rather than to the edge of the band
        # trade to the edge of the band == getting to the band edge while p_o=const

        # Cases when special conversion is not needed (to save on computations)
        if x == 0 or y == 0:
            if p_o > p_o_up:  # p_o < p_current_down
                # all to y at constant p_o, then to target currency adiabatically
                y_equiv: uint256 = y
                if y == 0:
                    y_equiv = x * 10**18 / p_current_mid
                if use_y:
                    XY += unsafe_div(y_equiv * user_share, total_share)
                else:
                    XY += unsafe_div(unsafe_div(y_equiv * p_o_up, SQRT_BAND_RATIO) * user_share, total_share)
                continue

            elif p_o < p_o_down:  # p_o > p_current_up
                # all to x at constant p_o, then to target currency adiabatically
                x_equiv: uint256 = x
                if x == 0:
                    x_equiv = unsafe_div(y * p_current_mid, 10**18)
                if use_y:
                    XY += unsafe_div(unsafe_div(x_equiv * SQRT_BAND_RATIO, p_o_up) * user_share, total_share)
                else:
                    XY += unsafe_div(x_equiv * user_share, total_share)
                continue

        # If we are here - we need to "trade" to somewhere mid-band
        # So we need more heavy math

        y0: uint256 = self._get_y0(x, y, p_o, p_o_up)
        f: uint256 = unsafe_div(unsafe_div(A * y0 * p_o, p_o_up) * p_o, 10**18)
        g: uint256 = unsafe_div(Aminus1 * y0 * p_o_up, p_o)
        # (f + x)(g + y) = const = p_top * A**2 * y0**2 = I
        Inv: uint256 = (f + x) * (g + y)
        # p = (f + x) / (g + y) => p * (g + y)**2 = I or (f + x)**2 / p = I

        # First, "trade" in this band to p_oracle
        x_o: uint256 = 0
        y_o: uint256 = 0

        if p_o > p_o_up:  # p_o < p_current_down, all to y
            # x_o = 0
            y_o = unsafe_sub(max(Inv / f, g), g)
            if use_y:
                XY += unsafe_div(y_o * user_share, total_share)
            else:
                XY += unsafe_div(unsafe_div(y_o * p_o_up, SQRT_BAND_RATIO) * user_share, total_share)

        elif p_o < p_o_down:  # p_o > p_current_up, all to x
            # y_o = 0
            x_o = unsafe_sub(max(Inv / g, f), f)
            if use_y:
                XY += unsafe_div(unsafe_div(x_o * SQRT_BAND_RATIO, p_o_up) * user_share, total_share)
            else:
                XY += unsafe_div(x_o * user_share, total_share)

        else:
            y_o = unsafe_sub(max(self.sqrt_int(unsafe_div(Inv * 10**18, p_o)), g), g)
            x_o = unsafe_sub(max(Inv / (g + y_o), f), f)
            # Now adiabatic conversion from definitely in-band
            if use_y:
                XY += unsafe_div((y_o + x_o * 10**18 / self.sqrt_int(p_o_up * p_o)) * user_share, total_share)

            else:
                XY += unsafe_div((x_o + unsafe_div(y_o * self.sqrt_int(p_o_down * p_o), 10**18)) * user_share, total_share)

    if use_y:
        return unsafe_div(XY, COLLATERAL_PRECISION)
    else:
        return unsafe_div(XY, BORROWED_PRECISION)


@external
@view
@nonreentrant('lock')
def get_y_up(user: address) -> uint256:
    """
    @notice Measure the amount of y (collateral) in the band n if we adiabatically trade near p_oracle on the way up
    @param user User the amount is calculated for
    @return Amount of coins
    """
    return self.get_xy_up(user, True)


@external
@view
@nonreentrant('lock')
def get_x_down(user: address) -> uint256:
    """
    @notice Measure the amount of x (stablecoin) if we trade adiabatically down
    @param user User the amount is calculated for
    @return Amount of coins
    """
    return self.get_xy_up(user, False)


@external
@view
@nonreentrant('lock')
def get_sum_xy(user: address) -> uint256[2]:
    """
    @notice A low-gas function to measure amounts of stablecoins and collateral which user currently owns
    @param user User address
    @return Amounts of (stablecoin, collateral) in a tuple
    """
    x: uint256 = 0
    y: uint256 = 0
    ns: int256[2] = self._read_user_tick_numbers(user)
    ticks: DynArray[uint256, MAX_TICKS_UINT] = self._read_user_ticks(user, ns)
    if ticks[0] == 0:
        return [0, 0]
    for i in range(MAX_TICKS):
        total_shares: uint256 = self.total_shares[ns[0]]
        x += self.bands_x[ns[0]] * ticks[i] / total_shares
        y += unsafe_div(self.bands_y[ns[0]] * ticks[i], total_shares)
        if ns[0] == ns[1]:
            break
        ns[0] += 1
    return [unsafe_div(x, BORROWED_PRECISION), unsafe_div(y, COLLATERAL_PRECISION)]


@external
@view
@nonreentrant('lock')
def get_amount_for_price(p: uint256) -> (uint256, bool):
    """
    @notice Amount necessary to be exchanged to have the AMM at the final price `p`
    @return (amount, is_pump)
    """
    min_band: int256 = self.min_band
    max_band: int256 = self.max_band
    n: int256 = self.active_band
    p_o: uint256 = self.price_oracle_contract.price()
    p_o_up: uint256 = self._p_oracle_up(n)
    p_down: uint256 = unsafe_div(unsafe_div(p_o**2, p_o_up) * p_o, p_o_up)  # p_current_down
    p_up: uint256 = unsafe_div(p_down * A2, Aminus12)  # p_crurrent_up
    amount: uint256 = 0
    y0: uint256 = 0
    f: uint256 = 0
    g: uint256 = 0
    Inv: uint256 = 0
    j: uint256 = MAX_TICKS_UINT
    pump: bool = True

    for i in range(MAX_TICKS + MAX_SKIP_TICKS):
        assert p_o_up > 0
        x: uint256 = self.bands_x[n]
        y: uint256 = self.bands_y[n]
        if i == 0:
            if p < self._get_p(n, x, y):
                pump = False
        not_empty: bool = x > 0 or y > 0
        if not_empty:
            y0 = self._get_y0(x, y, p_o, p_o_up)
            f = unsafe_div(unsafe_div(A * y0 * p_o, p_o_up) * p_o, 10**18)
            g = unsafe_div(Aminus1 * y0 * p_o_up, p_o)
            Inv = (f + x) * (g + y)
            if j == MAX_TICKS_UINT:
                j = 0

        if p <= p_up:
            if p >= p_down:
                if not_empty:
                    ynew: uint256 = unsafe_sub(max(self.sqrt_int(Inv * 10**18 / p), g), g)
                    xnew: uint256 = unsafe_sub(max(Inv / (g + ynew), f), f)
                    if pump:
                        amount += unsafe_sub(max(xnew, x), x)
                    else:
                        amount += unsafe_sub(max(ynew, y), y)
                break

        if pump:
            if not_empty:
                amount += (Inv / g - f) - x
            if n == max_band:
                break
            if j == MAX_TICKS_UINT - 1:
                break
            n += 1
            p_down = p_up
            p_up = unsafe_div(p_up * A2, Aminus12)
            p_o_up = unsafe_div(p_o_up * Aminus1, A)

        else:
            if not_empty:
                amount += (Inv / f - g) - y
            if n == min_band:
                break
            if j == MAX_TICKS_UINT - 1:
                break
            n -= 1
            p_up = p_down
            p_down = unsafe_div(p_down * Aminus12, A2)
            p_o_up = unsafe_div(p_o_up * A, Aminus1)

        if j != MAX_TICKS_UINT:
            j = unsafe_add(j, 1)

    amount = amount * 10**18 / unsafe_sub(10**18, self.fee)
    if amount == 0:
        return 0, pump

    # Precision and round up
    if pump:
        amount = unsafe_add(unsafe_div(unsafe_sub(amount, 1), BORROWED_PRECISION), 1)
    else:
        amount = unsafe_add(unsafe_div(unsafe_sub(amount, 1), COLLATERAL_PRECISION), 1)

    return amount, pump


@external
@nonreentrant('lock')
def set_rate(rate: uint256) -> uint256:
    """
    @notice Set interest rate. That affects the dependence of AMM base price over time
    @param rate New rate in units of int(fraction * 1e18) per second
    @return rate_mul multiplier (e.g. 1.0 + integral(rate, dt))
    """
    assert msg.sender == self.admin
    rate_mul: uint256 = self._rate_mul()
    self.rate_mul = rate_mul
    self.rate_time = block.timestamp
    self.rate = rate
    log SetRate(rate, rate_mul, block.timestamp)
    return rate_mul


@external
@nonreentrant('lock')
def set_fee(fee: uint256):
    """
    @notice Set AMM fee
    @param fee Fee where 1e18 == 100%
    """
    assert msg.sender == self.admin
    self.fee = fee
    log SetFee(fee)


@external
@nonreentrant('lock')
def set_admin_fee(fee: uint256):
    """
    @notice Set admin fee - fraction of the AMM fee to go to admin
    @param fee Admin fee where 1e18 == 100%
    """
    assert msg.sender == self.admin
    self.admin_fee = fee
    log SetAdminFee(fee)


@external
@nonreentrant('lock')
def reset_admin_fees():
    """
    @notice Zero out AMM fees collected
    """
    assert msg.sender == self.admin
    self.admin_fees_x = 0
    self.admin_fees_y = 0


@external
@nonreentrant('lock')
def set_price_oracle(price_oracle: PriceOracle):
    """
    @notice Set a new price oracle contract
    @param price_oracle Address of the new price oracle contract
    """
    assert msg.sender == self.admin
    self.price_oracle_contract = price_oracle
    log SetPriceOracle(price_oracle.address)


@external
def set_callback(liquidity_mining_callback: LMGauge):
    assert msg.sender == self.admin
    self.liquidity_mining_callback = liquidity_mining_callback
