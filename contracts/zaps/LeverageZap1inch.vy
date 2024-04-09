# @version 0.3.10

"""
@title LlamaLend and crvUSD leverage zap (using 1inch)
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Creates leverage on crvUSD via 1inch Router. Does calculations for leverage.
"""

interface ERC20:
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_for: address) -> uint256: view
    def allowance(_owner: address, _spender: address) -> uint256: view
    def approve(_spender: address, _value: uint256) -> bool: nonpayable
    def decimals() -> uint256: view

interface Factory:
    def controllers(i: uint256) -> address: view

interface Controller:
    def collateral_token() -> ERC20: view
    def loan_discount() -> uint256: view
    def amm() -> address: view
    def create_loan_extended(collateral: uint256, debt: uint256, N: uint256, callbacker: address, callback_args: DynArray[uint256,5]): nonpayable

interface LLAMMA:
    def A() -> uint256: view
    def coins(i: uint256) -> address: view
    def active_band() -> int256: view
    def get_base_price() -> uint256: view
    def price_oracle() -> uint256: view
    def p_oracle_up(n: int256) -> uint256: view
    def active_band_with_skip() -> int256: view


event Deposit:
    user: indexed(address)
    user_collateral: uint256
    user_borrowed: uint256
    user_collateral_from_borrowed: uint256
    debt: uint256
    leverage_collateral: uint256

event Repay:
    user: indexed(address)
    collateral_used: uint256
    borrowed_from_collateral: uint256
    user_borrowed: uint256


DEAD_SHARES: constant(uint256) = 1000
MAX_TICKS_UINT: constant(uint256) = 50
MAX_P_BASE_BANDS: constant(int256) = 5
MAX_SKIP_TICKS: constant(uint256) = 1024

ROUTER_1INCH: public(immutable(address))
FACTORIES: public(DynArray[address, 2])


@external
def __init__(_router_1inch: address, _factories: DynArray[address, 2]):
    ROUTER_1INCH = _router_1inch
    self.FACTORIES = _factories


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
def _get_k_effective(controller: address, collateral: uint256, N: uint256) -> uint256:
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
    # d_k_effective = 1 / N / sqrt(A / (A - 1))
    # d_k_effective: uint256 = 10**18 * unsafe_sub(10**18, discount) / (SQRT_BAND_RATIO * N)
    # Make some extra discount to always deposit lower when we have DEAD_SHARES rounding
    CONTROLLER: Controller = Controller(controller)
    A: uint256 = LLAMMA(CONTROLLER.amm()).A()
    SQRT_BAND_RATIO: uint256 = isqrt(unsafe_div(10 ** 36 * A, unsafe_sub(A, 1)))

    discount: uint256 = CONTROLLER.loan_discount()
    d_k_effective: uint256 = 10**18 * unsafe_sub(
        10**18, min(discount + (DEAD_SHARES * 10**18) / max(collateral / N, DEAD_SHARES), 10**18)
    ) / (SQRT_BAND_RATIO * N)
    k_effective: uint256 = d_k_effective
    for i in range(1, MAX_TICKS_UINT):
        if i == N:
            break
        d_k_effective = unsafe_div(d_k_effective * (A - 1), A)
        k_effective = unsafe_add(k_effective, d_k_effective)
    return k_effective


@internal
@view
def _max_p_base(controller: address) -> uint256:
    """
    @notice Calculate max base price including skipping bands
    """
    AMM: LLAMMA = LLAMMA(Controller(controller).amm())
    A: uint256 = AMM.A()
    LOG2_A_RATIO: int256 = self.log2(A * 10**18 / (A - 1))

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
        p_base = unsafe_div(p_base * A, A - 1)
        if p_base > p_oracle:
            return p_base_prev

    return p_base


@external
@view
def max_borrowable(controller: address, _user_collateral: uint256, _leverage_collateral: uint256, N: uint256, p_avg: uint256) -> uint256:
    """
    @notice Calculation of maximum which can be borrowed with leverage
    @param collateral Amount of collateral (at its native precision)
    @param N Number of bands to deposit into
    @param route_idx Index of the route which should be use for exchange stablecoin to collateral
    @return Maximum amount of stablecoin to borrow with leverage
    """
    # max_borrowable = collateral / (1 / (k_effective * max_p_base) - 1 / p_avg)
    AMM: LLAMMA = LLAMMA(Controller(controller).amm())
    BORROWED_TOKEN: address = AMM.coins(0)
    COLLATERAL_TOKEN: address = AMM.coins(1)
    COLLATERAL_PRECISION: uint256 = pow_mod256(10, 18 - ERC20(COLLATERAL_TOKEN).decimals())

    user_collateral: uint256 = _user_collateral * COLLATERAL_PRECISION
    leverage_collateral: uint256 = _leverage_collateral * COLLATERAL_PRECISION
    k_effective: uint256 = self._get_k_effective(controller, user_collateral + leverage_collateral, N)
    max_p_base: uint256 = self._max_p_base(controller)
    max_borrowable: uint256 = user_collateral * 10**18 / (10**36 / k_effective * 10**18 / max_p_base - 10**36 / p_avg)

    return min(max_borrowable * 999 / 1000, ERC20(BORROWED_TOKEN).balanceOf(controller)) # Cannot borrow beyond the amount of coins Controller has


@internal
def _transferFrom(token: address, _from: address, _to: address, amount: uint256):
    if amount > 0:
        assert ERC20(token).transferFrom(_from, _to, amount, default_return_value=True)


@internal
def _approve(coin: address, spender: address):
    if ERC20(coin).allowance(self, spender) == 0:
        ERC20(coin).approve(spender, max_value(uint256))


@external
@nonreentrant('lock')
def callback_deposit(user: address, callback_args: DynArray[uint256, 10], callback_bytes: Bytes[10**4]) -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param user Address of the user
    @param callback_args [stablecoins, user_collateral, d_debt, factory_id, controller_id, user_borrowed]
                         0. stablecoins is always 0
                         1. user_collateral - the amount of collateral token provided by user
                         2. d_debt - the amount to be borrowed (in addition to what has already been borrowed)
                         3-4. factory_id, controller_id are needed to check that msg.sender is the one of our controllers
                         5. user_borrowed - the amount of borrowed token provided by user (needs to be exchanged for collateral)
    return [0, user_collateral_from_borrowed + leverage_collateral]
    """
    controller: address = Factory(self.FACTORIES[callback_args[3]]).controllers(callback_args[4])
    assert msg.sender == controller, "wrong controller"
    amm: LLAMMA = LLAMMA(Controller(controller).amm())
    borrowed_token: address = amm.coins(0)
    collateral_token: address = amm.coins(1)

    self._approve(borrowed_token, ROUTER_1INCH)
    self._approve(collateral_token, controller)

    user_borrowed: uint256 = callback_args[5]
    self._transferFrom(borrowed_token, user, self, user_borrowed)
    raw_call(ROUTER_1INCH, callback_bytes)  # buys leverage_collateral for user_borrowed + dDebt
    additional_collateral: uint256 = ERC20(collateral_token).balanceOf(self)
    leverage_collateral: uint256 = callback_args[2] * 10**18 / (callback_args[2] + user_borrowed) * additional_collateral / 10**18
    user_collateral_from_borrowed: uint256 = additional_collateral - leverage_collateral

    log Deposit(user, callback_args[1], user_borrowed, user_collateral_from_borrowed, callback_args[2], leverage_collateral)

    return [0, additional_collateral]


@external
@nonreentrant('lock')
def callback_repay(user: address, callback_args: DynArray[uint256,10], callback_bytes: Bytes[10 ** 4]) -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param user Address of the user
    @param callback_args [stablecoins, collateral, debt, factory_id, controller_id, user_borrowed]
                         0-2. stablecoins, collateral, debt - values from user_state
                         3-4. factory_id, controller_id are needed to check that msg.sender is the one of our controllers
                         5. user_borrowed - the amount of borrowed token to repay from user's wallet
    return [user_borrowed + borrowed_from_collateral, remaining_collateral]
    """
    controller: address = Factory(self.FACTORIES[callback_args[3]]).controllers(callback_args[4])
    assert msg.sender == controller, "wrong controller"
    amm: LLAMMA = LLAMMA(Controller(controller).amm())
    borrowed_token: address = amm.coins(0)
    collateral_token: address = amm.coins(1)

    self._approve(collateral_token, ROUTER_1INCH)
    self._approve(borrowed_token, controller)
    self._approve(collateral_token, controller)

    initial_collateral: uint256 = ERC20(collateral_token).balanceOf(self)
    # Buys borrowed token for collateral from user's position. The amount to be spent is specified inside callback_bytes.
    raw_call(ROUTER_1INCH, callback_bytes)
    remaining_collateral: uint256 = ERC20(collateral_token).balanceOf(self)
    borrowed_from_collateral: uint256 = ERC20(borrowed_token).balanceOf(self)

    user_borrowed: uint256 = callback_args[5]
    self._transferFrom(borrowed_token, user, self, user_borrowed)

    log Repay(user, initial_collateral - remaining_collateral, borrowed_from_collateral, user_borrowed)

    return [borrowed_from_collateral + user_borrowed, remaining_collateral]
