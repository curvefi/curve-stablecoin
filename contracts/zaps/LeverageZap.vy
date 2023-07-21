# @version 0.3.7

interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def approve(_spender: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_for: address) -> uint256: view
    def decimals() -> uint256: view

interface Router:
    def exchange_multiple(_route: address[9], _swap_params: uint256[3][4], _amount: uint256, _expected: uint256, _pools: address[4]) -> uint256: payable
    def get_exchange_multiple_amount(_route: address[9], _swap_params: uint256[3][4], _amount: uint256, _pools: address[4]) -> uint256: view

interface Controller:
    def loan_discount() -> uint256: view
    def amm() -> address: view
    def calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256) -> int256: view

interface LLAMMA:
    def A() -> uint256: view
    def active_band() -> int256: view
    def can_skip_bands(n_end: int256) -> bool: view
    def get_base_price() -> uint256: view
    def price_oracle() -> uint256: view
    def p_oracle_up(n: int256) -> uint256: view
    def active_band_with_skip() -> int256: view


DEAD_SHARES: constant(uint256) = 1000
MAX_TICKS_UINT: constant(uint256) = 50
MAX_P_BASE_BANDS: constant(int256) = 5
MAX_SKIP_TICKS: constant(uint256) = 1024

CONTROLLER: immutable(address)
ROUTER: immutable(Router)
AMM: immutable(LLAMMA)
A: immutable(uint256)
Aminus1: immutable(uint256)
LOG2_A_RATIO: immutable(int256)  # log(A / (A - 1))
SQRT_BAND_RATIO: immutable(uint256)
COLLATERAL_PRECISION: immutable(uint256)

routes: public(HashMap[uint256, address[9]])
route_params: public(HashMap[uint256, uint256[3][4]])
route_pools: public(HashMap[uint256, address[4]])
route_names: public(HashMap[uint256, String[64]])
routes_count: public(uint256)


@external
def __init__(
        _controller: address,
        _crvusd: address,
        _collateral: address,
        _router: address,
        _routes: DynArray[address[9], 20],
        _route_params: DynArray[uint256[3][4], 20],
        _route_pools: DynArray[address[4], 20],
        _route_names: DynArray[String[64], 20],
):
    CONTROLLER = _controller
    ROUTER = Router(_router)

    amm: address = Controller(_controller).amm()
    AMM = LLAMMA(amm)
    _A: uint256 = LLAMMA(amm).A()
    A = _A
    Aminus1 = _A - 1
    LOG2_A_RATIO = self.log2(_A * 10 ** 18 / unsafe_sub(_A, 1))
    SQRT_BAND_RATIO = isqrt(unsafe_div(10 ** 36 * _A, unsafe_sub(_A, 1)))
    COLLATERAL_PRECISION = pow_mod256(10, 18 - ERC20(_collateral).decimals())

    for i in range(20):
        if i >= len(_routes):
            break
        self.routes[i] = _routes[i]
        self.route_params[i] = _route_params[i]
        self.route_pools[i] = _route_pools[i]
        self.route_names[i] = _route_names[i]
    self.routes_count = len(_routes)

    ERC20(_crvusd).approve(_controller, max_value(uint256), default_return_value=True)
    ERC20(_collateral).approve(_router, max_value(uint256), default_return_value=True)


@internal
@pure
def log2(_x: uint256) -> int256:
    """
    @notice int(1e18 * log2(_x / 1e18))
    """
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    # Might use more optimal solmate's log
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


@internal
@view
def _get_k_effective(collateral: uint256, N: uint256) -> uint256:
    """
    @notice Intermediary method which calculates k_effective defined as x_effective / p_base / y,
            however discounted by loan_discount.
            x_effective is an amount which can be obtained from collateral when liquidating
    @param N Number of bands the deposit is made into
    @return k_effective
    """
    # x_effective = sum_{i=0..N-1}(y / N * p(n_{n1+i})) =
    # = y / N * p_oracle_up(n1) * sqrt((A - 1) / A) * sum_{0..N-1}(((A-1) / A)**k)
    # === d_y_effective * p_oracle_up(n1) * sum(...) === y * k_effective * p_oracle_up(n1)
    # d_k_effective = N / sqrt(A / (A - 1))
    # d_k_effective: uint256 = 10**18 * unsafe_sub(10**18, discount) / (SQRT_BAND_RATIO * N)
    # Make some extra discount to always deposit lower when we have DEAD_SHARES rounding
    discount: uint256 = Controller(CONTROLLER).loan_discount()
    d_k_effective: uint256 = 10**18 * unsafe_sub(
        10**18, min(discount + (DEAD_SHARES * 10**18) / max(collateral / N, DEAD_SHARES), 10**18)
    ) / (SQRT_BAND_RATIO * N)
    k_effective: uint256 = d_k_effective
    for i in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        d_k_effective = unsafe_div(d_k_effective * Aminus1, A)
        k_effective = unsafe_add(k_effective, d_k_effective)
    return k_effective


@internal
@view
def _max_p_base() -> uint256:
    """
    @notice Calculate max base price including skipping bands
    """
    p_oracle: uint256 = AMM.price_oracle()
    # Should be correct unless price changes suddenly by MAX_P_BASE_BANDS+ bands
    n1: int256 = unsafe_div(self.log2(AMM.get_base_price() * 10**18 / p_oracle), LOG2_A_RATIO) + MAX_P_BASE_BANDS
    p_base: uint256 = AMM.p_oracle_up(n1)
    n_min: int256 = AMM.active_band_with_skip()

    for i in range(MAX_SKIP_TICKS + 1):
        n1 -= 1
        if n1 <= n_min:
            break
        p_base_prev: uint256 = p_base
        p_base = unsafe_div(p_base * A, Aminus1)
        if p_base > p_oracle:
            return p_base_prev

    return p_base


@view
@internal
def _get_collateral(stablecoin: uint256, route_idx: uint256) -> uint256:
    return ROUTER.get_exchange_multiple_amount(self.routes[route_idx], self.route_params[route_idx], stablecoin, self.route_pools[route_idx])


@view
@internal
def _get_collateral_and_avg_price(stablecoin: uint256, route_idx: uint256) -> uint256[2]:
    collateral: uint256 = self._get_collateral(stablecoin, route_idx)
    return [collateral, stablecoin * 10**18 / (collateral * COLLATERAL_PRECISION)]


@view
@external
@nonreentrant('lock')
def get_collateral(stablecoin: uint256, route_idx: uint256) -> uint256:
    return ROUTER.get_exchange_multiple_amount(self.routes[route_idx], self.route_params[route_idx], stablecoin, self.route_pools[route_idx])


@external
@view
def calculate_debt_n1(collateral: uint256, debt: uint256, N: uint256, route_idx: uint256) -> int256:
    """
        @notice Calculate the upper band number for the deposit to sit in to support
                the given debt with full leverage, which means that all borrowed
                stablecoin is converted to collateral coin and deposited in addition
                to collateral provided by user. Reverts if requested debt is too high.
        @param collateral Amount of collateral (at its native precision)
        @param debt Amount of requested debt
        @param N Number of bands to deposit into
        @param route_idx Index of the route which should be use for exchange stablecoin to collateral
        @return Upper band n1 (n1 <= n2) to deposit into. Signed integer
        """
    leverage_collateral: uint256 = self._get_collateral(debt, route_idx)
    return Controller(CONTROLLER).calculate_debt_n1(collateral + leverage_collateral, debt, N)


@external
@view
def max_borrowable(collateral: uint256, N: uint256, route_idx: uint256) -> uint256:
    """
        @notice Calculation of maximum which can be borrowed with leverage
        @param collateral Amount of collateral (at its native precision)
        @param N Number of bands to deposit into
        @param route_idx Index of the route which should be use for exchange stablecoin to collateral
        @return Maximum amount of stablecoin to borrow with leverage
        """
    # max_borrowable = collateral / (1 / (k_effective * max_p_base) - 1 / p_avg)
    user_collateral: uint256 = collateral * COLLATERAL_PRECISION
    leverage_collateral: uint256 = 0
    k_effective: uint256 = self._get_k_effective(user_collateral + leverage_collateral, N)
    max_p_base: uint256 = self._max_p_base()
    p_avg: uint256 = AMM.price_oracle()
    max_borrowable_prev: uint256 = 0
    max_borrowable: uint256 = 0
    for i in range(255):
        max_borrowable_prev = max_borrowable
        max_borrowable = user_collateral * 10**18 / (10**36 / k_effective * 10**18 / max_p_base - 10**36 / p_avg)
        if max_borrowable > max_borrowable_prev:
            if max_borrowable - max_borrowable_prev <= 1:
                return max_borrowable
        else:
            if max_borrowable_prev - max_borrowable <= 1:
                return max_borrowable
        res: uint256[2] = self._get_collateral_and_avg_price(max_borrowable, route_idx)
        leverage_collateral = res[0]
        p_avg = res[1]
        k_effective = self._get_k_effective(user_collateral + leverage_collateral, N)

    return max_borrowable


@external
@nonreentrant('lock')
def callback_deposit(user: address, stablecoins: uint256, collateral: uint256, debt: uint256, callback_args: DynArray[uint256, 5]) -> uint256[2]:
    assert msg.sender == CONTROLLER

    route_idx: uint256 = callback_args[0]
    min_recv: uint256 = callback_args[1]
    leverage_collateral: uint256 = ROUTER.exchange_multiple(self.routes[route_idx], self.route_params[route_idx], debt, min_recv, self.route_pools[route_idx])

    return [0, leverage_collateral]
