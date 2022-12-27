# @version 0.3.7

interface ERC20:
    def decimals() -> uint256: view
    def approve(_spender: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

interface LLAMMA:
    def A() -> uint256: view
    def coins(i: uint256) -> address: view
    def min_band() -> int256: view
    def max_band() -> int256: view
    def active_band() -> int256: view
    def bands_x(n: int256) -> uint256: view
    def bands_y(n: int256) -> uint256: view
    def p_oracle_up(n: int256) -> uint256: view
    def fee() -> uint256: view
    def admin_fee() -> uint256: view
    def price_oracle() -> uint256: view
    def exchange(i: uint256, j: uint256, in_amount: uint256, min_amount: uint256, _for: address) -> uint256: nonpayable

struct DetailedTrade:
    in_amount: uint256
    out_amount: uint256
    n1: int256
    n2: int256
    ticks_in: uint256[MAX_TICKS]
    last_tick_j: uint256
    admin_fee: uint256

MAX_TICKS: constant(int256) = 50
MAX_TICKS_UINT: constant(uint256) = 50
MAX_SKIP_TICKS: constant(int256) = 1024

allowance: public(HashMap[address, HashMap[address, bool]])


@internal
@pure
def sqrt_int(_x: uint256) -> uint256:
    """
    @notice Wrapping isqrt builtin because otherwise it will be repeated every time instead of calling
    @param _x Square root's input in "normal" units, e.g. sqrt_int(1) == 1
    """
    return isqrt(_x)


@internal
@view
def _get_y0(_llamma: address, x: uint256, y: uint256, p_o: uint256, p_o_up: uint256) -> uint256:
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
    _A: uint256 = LLAMMA(_llamma).A()
    _Aminus1: uint256 = unsafe_sub(_A, 1)
    # solve:
    # p_o * A * y0**2 - y0 * (p_oracle_up/p_o * (A-1) * x + p_o**2/p_oracle_up * A * y) - xy = 0
    b: uint256 = 0
    # p_o_up * unsafe_sub(A, 1) * x / p_o + A * p_o**2 / p_o_up * y / 10**18
    if x != 0:
        b = unsafe_div(p_o_up * _Aminus1 * x, p_o)
    if y != 0:
        b += unsafe_div(_A * p_o**2 / p_o_up * y, 10**18)
    if x > 0 and y > 0:
        D: uint256 = b**2 + unsafe_div(((4 * _A) * p_o) * y, 10**18) * x
        return unsafe_div((b + self.sqrt_int(D)) * 10**18, unsafe_mul(2 * _A, p_o))
    else:
        return unsafe_div(b * 10**18, _A * p_o)


@internal
@view
def calc_swap_in(_llamma: address, pump: bool, out_amount: uint256, p_o: uint256, in_precision: uint256, out_precision: uint256) -> DetailedTrade:
    """
    @notice Calculate the input amount required to receive the desired output amount.
            If couldn't exchange all - will also update the amount which was actually received.
            Also returns other parameters related to state after swap.
            This method is NOT PRECISE!
    @param pump Indicates whether the trade buys or sells collateral
    @param out_amount Desired amount of token going out
    @param p_o Current oracle price
    @return Amounts required and given out, initial and final bands of the AMM, new
            amounts of coins in bands in the AMM, as well as admin fee charged,
            all in one data structure
    """
    # pump = True: borrowable (USD) in, collateral (ETH) out; going up
    # pump = False: collateral (ETH) in, borrowable (USD) out; going down
    _A: uint256 = LLAMMA(_llamma).A()
    _Aminus1: uint256 = unsafe_sub(_A, 1)
    min_band: int256 = LLAMMA(_llamma).min_band()
    max_band: int256 = LLAMMA(_llamma).max_band()
    out: DetailedTrade = empty(DetailedTrade)
    out.n2 = LLAMMA(_llamma).active_band()
    p_o_up: uint256 = LLAMMA(_llamma).p_oracle_up(out.n2)
    x: uint256 = LLAMMA(_llamma).bands_x(out.n2)
    y: uint256 = LLAMMA(_llamma).bands_y(out.n2)

    out_amount_left: uint256 = out_amount
    antifee: uint256 = unsafe_div((10**18)**2, unsafe_sub(10**18, LLAMMA(_llamma).fee()))
    admin_fee: uint256 = LLAMMA(_llamma).admin_fee()
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
            y0 = self._get_y0(_llamma, x, y, p_o, p_o_up)  # <- also checks p_o
            f = unsafe_div(_A * y0 * p_o / p_o_up * p_o, 10**18)
            g = unsafe_div(_Aminus1 * y0 * p_o_up, p_o)
            Inv = (f + x) * (g + y)

        if pump:
            if y != 0:
                if g != 0:
                    if y >= out_amount_left:
                        # This is the last band
                        out.last_tick_j = y - out_amount_left  # Should be always >= 0
                        x_dest: uint256 = Inv / (g + out.last_tick_j) - f - x
                        dx: uint256 = unsafe_div(x_dest * antifee, 10**18)  # MORE than x_dest
                        x_dest = unsafe_div(unsafe_sub(dx, x_dest) * admin_fee, 10**18)  # abs admin fee now
                        out.out_amount = out_amount
                        out.ticks_in[j] = x + dx - x_dest
                        out.in_amount += dx
                        out.admin_fee = unsafe_add(out.admin_fee, x_dest)
                        break

                    else:
                        # We go into the next band
                        x_dest: uint256 = (unsafe_div(Inv, g) - f) - x
                        dx: uint256 = unsafe_div(x_dest * antifee, 10**18)
                        x_dest = unsafe_div(unsafe_sub(dx, x_dest) * admin_fee, 10**18)  # abs admin fee now
                        out_amount_left -= y
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
                p_o_up = unsafe_div(p_o_up * _Aminus1, _A)
                x = 0
                y = LLAMMA(_llamma).bands_y(out.n2)

        else:  # dump
            if x != 0:
                if f != 0:
                    if x >= out_amount_left:
                        # This is the last band
                        out.last_tick_j = x - out_amount_left
                        y_dest: uint256 = Inv / (f + out.last_tick_j) - g - y
                        dy: uint256 = unsafe_div(y_dest * antifee, 10**18)  # MORE than y_dest
                        y_dest = unsafe_div(unsafe_sub(dy, y_dest) * admin_fee, 10**18)  # abs admin fee now
                        out.out_amount = out_amount
                        out.ticks_in[j] = y + dy - y_dest
                        out.in_amount += dy
                        out.admin_fee = unsafe_add(out.admin_fee, y_dest)
                        break

                    else:
                        # We go into the next band
                        y_dest: uint256 = (unsafe_div(Inv, f) - g) - y
                        dy: uint256 = unsafe_div(y_dest * antifee, 10**18)
                        y_dest = unsafe_div(unsafe_sub(dy, y_dest) * admin_fee, 10**18)  # abs admin fee now
                        out_amount_left -= x
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
                p_o_up = unsafe_div(p_o_up * _A, _Aminus1)
                x = LLAMMA(_llamma).bands_x(out.n2)
                y = 0

        if j != MAX_TICKS_UINT:
            j = unsafe_add(j, 1)

    # Round up what goes in and down what goes out
    # ceil(in_amount_used/BORROWED_PRECISION) * BORROWED_PRECISION
    out.in_amount = unsafe_mul(unsafe_div(unsafe_add(out.in_amount, unsafe_sub(in_precision, 1)), in_precision), in_precision)
    out.out_amount = unsafe_mul(unsafe_div(out.out_amount, out_precision), out_precision)

    # If out_amount is zeroed because of rounding off - don't charge admin fees
    if out.out_amount == 0:
        out.admin_fee = 0

    return out


@internal
@view
def _get_dydx(_llamma: address, i: uint256, j: uint256, out_amount: uint256) -> DetailedTrade:
    """
    @notice Method to use to calculate in amount required and out amount received
    @param i Input coin index
    @param j Output coin index
    @param out_amount Desired amount of output coin to receive
    @return DetailedTrade with all swap results
    """
    # i = 0: borrowable (USD) in, collateral (ETH) out; going up
    # i = 1: collateral (ETH) in, borrowable (USD) out; going down
    assert (i == 0 and j == 1) or (i == 1 and j == 0), "Wrong index"
    out: DetailedTrade = empty(DetailedTrade)
    if out_amount == 0:
        return out
    _borrowed: address = LLAMMA(_llamma).coins(0)
    _collateral: address = LLAMMA(_llamma).coins(1)
    _COLLATERAL_PRECISION: uint256 = 10**(18 - ERC20(_collateral).decimals())
    _BORROWED_PRECISION: uint256 = 10**(18 - ERC20(_borrowed).decimals())
    in_precision: uint256 = _COLLATERAL_PRECISION
    out_precision: uint256 = _BORROWED_PRECISION
    if i == 0:
        in_precision = _BORROWED_PRECISION
        out_precision = _COLLATERAL_PRECISION
    out = self.calc_swap_in(_llamma, i == 0, out_amount * out_precision, LLAMMA(_llamma).price_oracle(), in_precision, out_precision)
    out.in_amount = unsafe_div(out.in_amount, in_precision)
    out.out_amount = unsafe_div(out.out_amount, out_precision)
    return out


@external
@view
@nonreentrant('lock')
def get_dx(_llamma: address, i: uint256, j: uint256, out_amount: uint256) -> uint256:
    """
    @notice Method to use to calculate in amount required to receive the desired out_amount
    @param i Input coin index
    @param j Output coin index
    @param out_amount Desired amount of output coin to receive
    @return Amount of coin i to spend
    """
    # i = 0: borrowable (USD) in, collateral (ETH) out; going up
    # i = 1: collateral (ETH) in, borrowable (USD) out; going down
    return self._get_dydx(_llamma, i, j, out_amount).in_amount


@external
@view
@nonreentrant('lock')
def get_dydx(_llamma: address, i: uint256, j: uint256, out_amount: uint256) -> (uint256, uint256):
    """
    @notice Method to use to calculate in amount required and out amount received
    @param i Input coin index
    @param j Output coin index
    @param out_amount Desired amount of output coin to receive
    @return A tuple with out_amount received and in_amount returned
    """
    # i = 0: borrowable (USD) in, collateral (ETH) out; going up
    # i = 1: collateral (ETH) in, borrowable (USD) out; going down
    out: DetailedTrade = self._get_dydx(_llamma, i, j, out_amount)
    return (out.out_amount, out.in_amount)


@external
@nonreentrant('lock')
def exchange_dy(_llamma: address, i: uint256, j: uint256, out_amount: uint256, min_amount: uint256, _for: address = msg.sender) -> uint256:
    """
    @notice Exchanges two coins to get desired out_amount, callable by anyone.
            Actual received amount can be slightly different from passed out_amount even if no slippage.
    @param _llamma AMM address
    @param i Input coin index
    @param j Output coin index
    @param out_amount Desired amount of output coin to receive
    @param min_amount Minimal amount to get as output (revert if less)
    @param _for Address to send coins to
    @return Amount of coins given out
    """
    # i = 0: borrowable (USD) in, collateral (ETH) out; going up
    # i = 1: collateral (ETH) in, borrowable (USD) out; going down
    out: DetailedTrade = self._get_dydx(_llamma, i, j, out_amount) # <- also checks i,j and out_amount == 0
    if out.in_amount == 0:
        return 0

    BORROWED_TOKEN: address = LLAMMA(_llamma).coins(0)
    COLLATERAL_TOKEN: address = LLAMMA(_llamma).coins(1)
    in_coin: address = BORROWED_TOKEN
    if i == 1:
        in_coin = COLLATERAL_TOKEN

    if not self.allowance[_llamma][in_coin]:
        self.allowance[_llamma][in_coin] = True
        ERC20(in_coin).approve(_llamma, MAX_UINT256)

    assert ERC20(in_coin).transferFrom(msg.sender, self, out.in_amount, default_return_value=True)
    return LLAMMA(_llamma).exchange(i, j, out.in_amount, min_amount, _for)
