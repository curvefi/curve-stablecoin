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

interface LLAMMA:
    def A() -> uint256: view
    def active_band() -> int256: view
    def can_skip_bands(n_end: int256) -> bool: view
    def get_base_price() -> uint256: view
    def price_oracle() -> uint256: view
    def p_oracle_up(n: int256) -> uint256: view


DEAD_SHARES: constant(uint256) = 1000
MAX_TICKS_UINT: constant(uint256) = 50

CONTROLLER_ADDRESS: immutable(address)
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
    CONTROLLER_ADDRESS = _controller
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
    discount: uint256 = Controller(CONTROLLER_ADDRESS).loan_discount()
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


@view
@internal
def _calc_collateral_and_avg_price(debt: uint256, route_idx: uint256) -> uint256[2]:
    collateral: uint256 = ROUTER.get_exchange_multiple_amount(self.routes[route_idx], self.route_params[route_idx], debt, self.route_pools[route_idx])
    return [collateral, debt * 10**18 / (collateral * COLLATERAL_PRECISION)]


@external
@view
def calculate_leverage_n1(collateral: uint256, debt: uint256, N: uint256, route_idx: uint256) -> int256:
    """
        @notice Calculate the upper band number for the deposit to sit in to support
                the given debt. Reverts if requested debt is too high.
        @param collateral Amount of collateral (at its native precision)
        @param debt Amount of requested debt
        @param N Number of bands to deposit into
        @return Upper band n1 (n1 <= n2) to deposit into. Signed integer
        """
    assert debt > 0, "No loan"
    n0: int256 = AMM.active_band()
    p_base: uint256 = AMM.p_oracle_up(n0)
    user_collateral: uint256 = collateral * COLLATERAL_PRECISION

    res: uint256[2] = self._calc_collateral_and_avg_price(debt, route_idx)
    leverage_collateral: uint256 = res[0] * COLLATERAL_PRECISION
    p_avg: uint256 = res[1]
    k_effective: uint256 = self._get_k_effective(user_collateral + leverage_collateral, N)
    # p_oracle_up(n1) = base_price * ((A - 1) / A)**n1

    # We borrow up until min band touches p_oracle,
    # or it touches non-empty bands which cannot be skipped.
    # We calculate required n1 for given (collateral, debt),
    # and if n1 corresponds to price_oracle being too high, or unreachable band
    # - we revert.


    # p_base * ((A - 1) / A)**n1 = 1 / k_effective * 1 / (collateral/debt + 1/p_avg) =>
    # => n1 = floor(log2((collateral * p_base / debt + p_base / p_avg) / k_effective) / LOG2_A_RATIO)

    # n1 is band number based on adiabatic trading, e.g. when p_oracle ~ p

    # n1 = floor(log2(y_effective) / self.logAratio)
    # EVM semantics is not doing floor unlike Python, so we do this
    assert k_effective > 0, "Amount too low"
    n1: int256 = self.log2((user_collateral * p_base / debt + p_base * 10**18 / p_avg) * k_effective / 10**18)
    if n1 < 0:
        n1 -= LOG2_A_RATIO - 1  # This is to deal with vyper's rounding of negative numbers
    n1 /= LOG2_A_RATIO

    n1 = min(n1, 1024 - convert(N, int256)) + n0
    if n1 <= n0:
        assert AMM.can_skip_bands(n1 - 1), "Debt too high"

    # Let's not rely on active_band corresponding to price_oracle:
    # this will be not correct if we are in the area of empty bands
    assert AMM.p_oracle_up(n1) < AMM.price_oracle(), "Debt too high"

    return n1


@view
@external
@nonreentrant('lock')
def calc_output(debt: uint256, route_idx: uint256) -> uint256:
    return ROUTER.get_exchange_multiple_amount(self.routes[route_idx], self.route_params[route_idx], debt, self.route_pools[route_idx])


@external
@nonreentrant('lock')
def callback_deposit(user: address, stablecoins: uint256, collateral: uint256, debt: uint256, callback_args: DynArray[uint256, 5]) -> uint256[2]:
    assert msg.sender == CONTROLLER_ADDRESS

    route_idx: uint256 = callback_args[0]
    min_recv: uint256 = callback_args[1]
    leverage_collateral: uint256 = ROUTER.exchange_multiple(self.routes[route_idx], self.route_params[route_idx], debt, min_recv, self.route_pools[route_idx])

    return [0, leverage_collateral]
