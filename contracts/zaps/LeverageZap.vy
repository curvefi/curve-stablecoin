# @version 0.3.10

"""
@title LlamaLendLeverageZap
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Creates leverage on LlamaLend and crvUSD markets via Aggregator Router. Does calculations for leverage.
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
    state_collateral_used: uint256
    borrowed_from_state_collateral: uint256
    user_collateral: uint256
    user_collateral_used: uint256
    borrowed_from_user_collateral: uint256
    user_borrowed: uint256


DEAD_SHARES: constant(uint256) = 1000
MAX_TICKS_UINT: constant(uint256) = 50
MAX_P_BASE_BANDS: constant(int256) = 5
MAX_SKIP_TICKS: constant(uint256) = 1024

ROUTER: public(immutable(address))
FACTORIES: public(DynArray[address, 2])


@external
def __init__(_router: address, _factories: DynArray[address, 2]):
    ROUTER = _router
    self.FACTORIES = _factories


@internal
@pure
def _log_2(x: uint256) -> uint256:
    """
    @dev An `internal` helper function that returns the log in base 2
         of `x`, following the selected rounding direction.
    @notice Note that it returns 0 if given 0. The implementation is
            inspired by OpenZeppelin's implementation here:
            https://github.com/OpenZeppelin/openzeppelin-contracts/blob/master/contracts/utils/math/Math.sol.
            This code is taken from snekmate.
    @param x The 32-byte variable.
    @return uint256 The 32-byte calculation result.
    """
    value: uint256 = x
    result: uint256 = empty(uint256)

    # The following lines cannot overflow because we have the well-known
    # decay behaviour of `log_2(max_value(uint256)) < max_value(uint256)`.
    if (x >> 128 != empty(uint256)):
        value = x >> 128
        result = 128
    if (value >> 64 != empty(uint256)):
        value = value >> 64
        result = unsafe_add(result, 64)
    if (value >> 32 != empty(uint256)):
        value = value >> 32
        result = unsafe_add(result, 32)
    if (value >> 16 != empty(uint256)):
        value = value >> 16
        result = unsafe_add(result, 16)
    if (value >> 8 != empty(uint256)):
        value = value >> 8
        result = unsafe_add(result, 8)
    if (value >> 4 != empty(uint256)):
        value = value >> 4
        result = unsafe_add(result, 4)
    if (value >> 2 != empty(uint256)):
        value = value >> 2
        result = unsafe_add(result, 2)
    if (value >> 1 != empty(uint256)):
        result = unsafe_add(result, 1)

    return result


@internal
@pure
def wad_ln(x: uint256) -> int256:
    """
    @dev Calculates the natural logarithm of a signed integer with a
         precision of 1e18.
    @notice Note that it returns 0 if given 0. Furthermore, this function
            consumes about 1,400 to 1,650 gas units depending on the value
            of `x`. The implementation is inspired by Remco Bloemen's
            implementation under the MIT license here:
            https://xn--2-umb.com/22/exp-ln.
            This code is taken from snekmate.
    @param x The 32-byte variable.
    @return int256 The 32-byte calculation result.
    """
    value: int256 = convert(x, int256)

    assert x > 0

    # We want to convert `x` from "10 ** 18" fixed point to "2 ** 96"
    # fixed point. We do this by multiplying by "2 ** 96 / 10 ** 18".
    # But since "ln(x * C) = ln(x) + ln(C)" holds, we can just do nothing
    # here and add "ln(2 ** 96 / 10 ** 18)" at the end.

    # Reduce the range of `x` to "(1, 2) * 2 ** 96".
    # Also remember that "ln(2 ** k * x) = k * ln(2) + ln(x)" holds.
    k: int256 = unsafe_sub(convert(self._log_2(x), int256), 96)
    # Note that to circumvent Vyper's safecast feature for the potentially
    # negative expression `value <<= uint256(159 - k)`, we first convert the
    # expression `value <<= uint256(159 - k)` to `bytes32` and subsequently
    # to `uint256`. Remember that the EVM default behaviour is to use two's
    # complement representation to handle signed integers.
    value = convert(convert(convert(value << convert(unsafe_sub(159, k), uint256), bytes32), uint256) >> 159, int256)

    # Evaluate using a "(8, 8)"-term rational approximation. Since `p` is monic,
    # we will multiply by a scaling factor later.
    p: int256 = unsafe_add(unsafe_mul(unsafe_add(value, 3_273_285_459_638_523_848_632_254_066_296), value) >> 96, 24_828_157_081_833_163_892_658_089_445_524)
    p = unsafe_add(unsafe_mul(p, value) >> 96, 43_456_485_725_739_037_958_740_375_743_393)
    p = unsafe_sub(unsafe_mul(p, value) >> 96, 11_111_509_109_440_967_052_023_855_526_967)
    p = unsafe_sub(unsafe_mul(p, value) >> 96, 45_023_709_667_254_063_763_336_534_515_857)
    p = unsafe_sub(unsafe_mul(p, value) >> 96, 14_706_773_417_378_608_786_704_636_184_526)
    p = unsafe_sub(unsafe_mul(p, value), 795_164_235_651_350_426_258_249_787_498 << 96)

    # We leave `p` in the "2 ** 192" base so that we do not have to scale it up
    # again for the division. Note that `q` is monic by convention.
    q: int256 = unsafe_add(unsafe_mul(unsafe_add(value, 5_573_035_233_440_673_466_300_451_813_936), value) >> 96, 71_694_874_799_317_883_764_090_561_454_958)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 283_447_036_172_924_575_727_196_451_306_956)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 401_686_690_394_027_663_651_624_208_769_553)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 204_048_457_590_392_012_362_485_061_816_622)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 31_853_899_698_501_571_402_653_359_427_138)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 909_429_971_244_387_300_277_376_558_375)

    # It is known that the polynomial `q` has no zeros in the domain.
    # No scaling is required, as `p` is already "2 ** 96" too large. Also,
    # `r` is in the range "(0, 0.125) * 2 ** 96" after the division.
    r: int256 = unsafe_div(p, q)

    # To finalise the calculation, we have to proceed with the following steps:
    #   - multiply by the scaling factor "s = 5.549...",
    #   - add "ln(2 ** 96 / 10 ** 18)",
    #   - add "k * ln(2)", and
    #   - multiply by "10 ** 18 / 2 ** 96 = 5 ** 18 >> 78".
    # In order to perform the most gas-efficient calculation, we carry out all
    # these steps in one expression.
    return unsafe_add(unsafe_add(unsafe_mul(r, 1_677_202_110_996_718_588_342_820_967_067_443_963_516_166),\
           unsafe_mul(k, 16_597_577_552_685_614_221_487_285_958_193_947_469_193_820_559_219_878_177_908_093_499_208_371)),\
           600_920_179_829_731_861_736_702_779_321_621_459_595_472_258_049_074_101_567_377_883_020_018_308) >> 174


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
    LOGN_A_RATIO: int256 = self.wad_ln(A * 10**18 / (A - 1))

    p_oracle: uint256 = AMM.price_oracle()
    # Should be correct unless price changes suddenly by MAX_P_BASE_BANDS+ bands
    n1: int256 = self.wad_ln(AMM.get_base_price() * 10**18 / p_oracle)
    if n1 < 0:
        n1 -= LOGN_A_RATIO - 1  # This is to deal with vyper's rounding of negative numbers
    n1 = unsafe_div(n1, LOGN_A_RATIO) + MAX_P_BASE_BANDS
    n_min: int256 = AMM.active_band_with_skip()
    n1 = max(n1, n_min + 1)
    p_base: uint256 = AMM.p_oracle_up(n1)

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
    # TODO: use contracts.lib.token_lib.transferFrom
    if amount > 0:
        assert ERC20(token).transferFrom(_from, _to, amount, default_return_value=True)


@internal
def _approve(coin: address, spender: address):
    # TODO: use contracts.lib.token_lib.max_approve
    if ERC20(coin).allowance(self, spender) == 0:
        assert ERC20(coin).approve(spender, max_value(uint256), default_return_value=True)


@external
@nonreentrant('lock')
def callback_deposit(user: address, borrowed: uint256, user_collateral: uint256, d_debt: uint256,
                     callback_args: DynArray[uint256, 10], callback_bytes: Bytes[10**4] = b"") -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param user Address of the user
    @param borrowed Always 0
    @param user_collateral The amount of collateral token provided by user
    @param d_debt The amount to be borrowed (in addition to what has already been borrowed)
    @param callback_args [factory_id, controller_id, user_borrowed]
                         0-1. factory_id, controller_id are needed to check that msg.sender is the one of our controllers
                         2. user_borrowed - the amount of borrowed token provided by user (needs to be exchanged for collateral)
    return [0, user_collateral_from_borrowed + leverage_collateral]
    """
    controller: address = Factory(self.FACTORIES[callback_args[0]]).controllers(callback_args[1])
    assert msg.sender == controller, "wrong controller"
    amm: LLAMMA = LLAMMA(Controller(controller).amm())
    borrowed_token: address = amm.coins(0)
    collateral_token: address = amm.coins(1)

    self._approve(borrowed_token, ROUTER)
    self._approve(collateral_token, controller)

    user_borrowed: uint256 = callback_args[2]
    self._transferFrom(borrowed_token, user, self, user_borrowed)
    raw_call(ROUTER, callback_bytes)  # buys leverage_collateral for user_borrowed + dDebt
    additional_collateral: uint256 = ERC20(collateral_token).balanceOf(self)
    leverage_collateral: uint256 = d_debt * 10**18 / (d_debt + user_borrowed) * additional_collateral / 10**18
    user_collateral_from_borrowed: uint256 = additional_collateral - leverage_collateral

    log Deposit(user, user_collateral, user_borrowed, user_collateral_from_borrowed, d_debt, leverage_collateral)

    return [0, additional_collateral]


@external
@nonreentrant('lock')
def callback_repay(user: address, borrowed: uint256, collateral: uint256, debt: uint256,
                   callback_args: DynArray[uint256,10], callback_bytes: Bytes[10 ** 4] = b"") -> uint256[2]:
    """
    @notice Callback method which should be called by controller to create leveraged position
    @param user Address of the user
    @param borrowed The value from user_state
    @param collateral The value from user_state
    @param debt The value from user_state
    @param callback_args [factory_id, controller_id, user_collateral, user_borrowed]
                         0-1. factory_id, controller_id are needed to check that msg.sender is the one of our controllers
                         2. user_collateral - the amount of collateral token provided by user (needs to be exchanged for borrowed)
                         3. user_borrowed - the amount of borrowed token to repay from user's wallet
    return [user_borrowed + borrowed_from_collateral, remaining_collateral]
    """
    controller: address = Factory(self.FACTORIES[callback_args[0]]).controllers(callback_args[1])
    assert msg.sender == controller, "wrong controller"
    amm: LLAMMA = LLAMMA(Controller(controller).amm())
    borrowed_token: address = amm.coins(0)
    collateral_token: address = amm.coins(1)

    self._approve(collateral_token, ROUTER)
    self._approve(borrowed_token, controller)
    self._approve(collateral_token, controller)

    initial_collateral: uint256 = ERC20(collateral_token).balanceOf(self)
    user_collateral: uint256 = callback_args[2]
    if callback_bytes != b"":
        self._transferFrom(collateral_token, user, self, user_collateral)
        # Buys borrowed token for collateral from user's position + from user's wallet.
        # The amount to be spent is specified inside callback_bytes.
        raw_call(ROUTER, callback_bytes)
    else:
        assert user_collateral == 0
    remaining_collateral: uint256 = ERC20(collateral_token).balanceOf(self)
    state_collateral_used: uint256 = 0
    borrowed_from_state_collateral: uint256 = 0
    user_collateral_used: uint256 = user_collateral
    borrowed_from_user_collateral: uint256 = ERC20(borrowed_token).balanceOf(self)  # here it's total borrowed_from_collateral
    if remaining_collateral < initial_collateral:
        state_collateral_used = initial_collateral - remaining_collateral
        borrowed_from_state_collateral = state_collateral_used * 10**18 / (state_collateral_used + user_collateral_used) * borrowed_from_user_collateral / 10**18
        borrowed_from_user_collateral = borrowed_from_user_collateral - borrowed_from_state_collateral
    else:
        user_collateral_used = user_collateral - (remaining_collateral - initial_collateral)

    user_borrowed: uint256 = callback_args[3]
    self._transferFrom(borrowed_token, user, self, user_borrowed)

    log Repay(user, state_collateral_used, borrowed_from_state_collateral, user_collateral, user_collateral_used, borrowed_from_user_collateral, user_borrowed)

    return [borrowed_from_state_collateral + borrowed_from_user_collateral + user_borrowed, remaining_collateral]
