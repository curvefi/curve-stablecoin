# pragma version 0.4.3
# pragma nonreentrancy on
# pragma optimize codesize
"""
@title crvUSD Controller
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from contracts.interfaces import IAMM
from contracts.interfaces import ILMGauge
from contracts.interfaces import IMonetaryPolicy
from contracts.interfaces import IFactory

from contracts.interfaces import IController

implements: IController
from contracts.interfaces import IMintController

from snekmate.utils import math
from contracts import controller_core as ctrl

initializes: ctrl

exports: (
    ctrl.amm,
    ctrl.amm_price,
    ctrl.approval,
    ctrl.approve,
    ctrl.borrowed_token,
    ctrl.calculate_debt_n1,
    ctrl.collateral_token,
    ctrl.debt,
    ctrl.extra_health,
    ctrl.health,
    ctrl.health_calculator,
    ctrl.liquidation_discount,
    ctrl.liquidation_discounts,
    ctrl.loan_discount,
    ctrl.loan_exists,
    ctrl.loan_ix,
    ctrl.loans,
    ctrl.min_collateral,
    ctrl.monetary_policy,
    ctrl.n_loans,
    ctrl.save_rate,
    ctrl.set_extra_health,
    ctrl.tokens_to_liquidate,
    ctrl.total_debt,
    ctrl.user_prices,
    ctrl.user_state,
    ctrl.users_to_liquidate,
)

FACTORY: immutable(IFactory)

minted: public(uint256)
redeemed: public(uint256)


@deploy
def __init__(
    collateral_token: IERC20,
    monetary_policy: IMonetaryPolicy,
    loan_discount: uint256,
    liquidation_discount: uint256,
    amm: IAMM,
):
    """
    @notice Controller constructor deployed by the factory from blueprint
    @param collateral_token Token to use for collateral
    @param monetary_policy Address of monetary policy
    @param loan_discount Discount of the maximum loan size compare to get_x_down() value
    @param liquidation_discount Discount of the maximum loan size compare to
           get_x_down() for "bad liquidation" purposes
    @param amm AMM address (Already deployed from blueprint)
    """
    FACTORY = IFactory(msg.sender)

    borrowed_token: IERC20 = staticcall FACTORY.stablecoin()

    ctrl.__init__(
        amm,
        collateral_token,
        borrowed_token,
        monetary_policy,
        loan_discount,
        liquidation_discount,
    )


@external
@view
def factory() -> address:
    """
    @notice Address of the factory
    """
    return FACTORY.address


@external
@view
def max_borrowable(
    collateral: uint256,
    N: uint256,
    current_debt: uint256 = 0,
    user: address = empty(address),
) -> uint256:
    """
    @notice Calculation of maximum which can be borrowed (details in comments)
    @param collateral Collateral amount against which to borrow
    @param N number of bands to have the deposit into
    @param current_debt Current debt of the user (if any)
    @param user User to calculate the value for (only necessary for nonzero extra_health)
    @return Maximum amount of stablecoin to borrow
    """
    # Calculation of maximum which can be borrowed.
    # It corresponds to a minimum between the amount corresponding to price_oracle
    # and the one given by the min reachable band.
    #
    # Given by p_oracle (perhaps needs to be multiplied by (A - 1) / A to account for mid-band effects)
    # x_max ~= y_effective * p_oracle
    #
    # Given by band number:
    # if n1 is the lowest empty band in the AMM
    # xmax ~= y_effective * amm.p_oracle_up(n1)
    #
    # When n1 -= 1:
    # p_oracle_up *= A / (A - 1)
    # if N < MIN_TICKS or N > MAX_TICKS:
    assert N >= ctrl.MIN_TICKS_UINT and N <= ctrl.MAX_TICKS_UINT

    y_effective: uint256 = ctrl.get_y_effective(
        collateral * ctrl.COLLATERAL_PRECISION,
        N,
        ctrl.loan_discount + ctrl.extra_health[user],
    )

    x: uint256 = unsafe_sub(
        max(unsafe_div(y_effective * ctrl.max_p_base(), 10**18), 1), 1
    )
    x = unsafe_div(
        x * (10**18 - 10**14), unsafe_mul(10**18, ctrl.BORROWED_PRECISION)
    )  # Make it a bit smaller
    # TODO need to port cap?
    return min(
        x, staticcall ctrl.BORROWED_TOKEN.balanceOf(self) + current_debt
    )  # Cannot borrow beyond the amount of coins Controller has


@internal
def _create_loan(collateral: uint256, debt: uint256, N: uint256, _for: address):
    assert ctrl.loan[_for].initial_debt == 0, "Loan already created"
    assert N > ctrl.MIN_TICKS_UINT - 1, "Need more ticks"
    assert N < ctrl.MAX_TICKS_UINT + 1, "Need less ticks"

    n1: int256 = ctrl._calculate_debt_n1(collateral, debt, N, _for)
    n2: int256 = n1 + convert(unsafe_sub(N, 1), int256)

    rate_mul: uint256 = staticcall ctrl.AMM.get_rate_mul()
    ctrl.loan[_for] = IController.Loan(initial_debt=debt, rate_mul=rate_mul)
    liquidation_discount: uint256 = ctrl.liquidation_discount
    ctrl.liquidation_discounts[_for] = liquidation_discount

    n_loans: uint256 = ctrl.n_loans
    ctrl.loans[n_loans] = _for
    ctrl.loan_ix[_for] = n_loans
    ctrl.n_loans = unsafe_add(n_loans, 1)

    ctrl._total_debt.initial_debt = (
        ctrl._total_debt.initial_debt * rate_mul // ctrl._total_debt.rate_mul
        + debt
    )
    ctrl._total_debt.rate_mul = rate_mul

    extcall ctrl.AMM.deposit_range(_for, collateral, n1, n2)
    self.minted += debt

    ctrl._save_rate()

    log IController.UserState(
        user=_for,
        collateral=collateral,
        debt=debt,
        n1=n1,
        n2=n2,
        liquidation_discount=liquidation_discount,
    )
    log IController.Borrow(
        user=_for, collateral_increase=collateral, loan_increase=debt
    )


@external
def create_loan(
    collateral: uint256,
    debt: uint256,
    N: uint256,
    _for: address = msg.sender,
    callbacker: address = empty(address),
    calldata: Bytes[10**4] = b"",
):
    """
    @notice Create loan but pass stablecoin to a callback first so that it can build leverage
    @param collateral Amount of collateral to use
    @param debt Stablecoin debt to take
    @param N Number of bands to deposit into (to do autoliquidation-deliquidation),
           can be from MIN_TICKS to MAX_TICKS
    @param _for Address to create the loan for
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    if _for != tx.origin:
        # We can create a loan for tx.origin (for example when wrapping ETH with EOA),
        # however need to approve in other cases
        assert ctrl._check_approval(_for)

    more_collateral: uint256 = 0
    if callbacker != empty(address):
        ctrl.transfer(ctrl.BORROWED_TOKEN, callbacker, debt)
        # If there is any unused debt, callbacker can send it to the user
        more_collateral = ctrl.execute_callback(
            callbacker,
            ctrl.CALLBACK_DEPOSIT,
            _for,
            0,
            collateral,
            debt,
            calldata,
        ).collateral

    self._create_loan(collateral + more_collateral, debt, N, _for)

    ctrl.transferFrom(
        ctrl.COLLATERAL_TOKEN, msg.sender, ctrl.AMM.address, collateral
    )
    if more_collateral > 0:
        ctrl.transferFrom(
            ctrl.COLLATERAL_TOKEN, callbacker, ctrl.AMM.address, more_collateral
        )
    if callbacker == empty(address):
        ctrl.transfer(ctrl.BORROWED_TOKEN, _for, debt)


@internal
def _add_collateral_borrow(
    d_collateral: uint256,
    d_debt: uint256,
    _for: address,
    remove_collateral: bool,
    check_rounding: bool,
):
    """
    @notice Internal method to borrow and add or remove collateral
    @param d_collateral Amount of collateral to add
    @param d_debt Amount of debt increase
    @param _for Address to transfer tokens to
    @param remove_collateral Remove collateral instead of adding
    @param check_rounding Check that amount added is no less than the rounding error on the loan
    """
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = ctrl._debt(_for)
    assert debt > 0, "Loan doesn't exist"
    debt += d_debt

    xy: uint256[2] = extcall ctrl.AMM.withdraw(_for, 10**18)
    assert xy[0] == 0, "Already in underwater mode"
    if remove_collateral:
        xy[1] -= d_collateral
    else:
        xy[1] += d_collateral
        if check_rounding:
            # We need d(x + p*y) > 1 wei. For that, we do an equivalent check (but with x2 for safety)
            # This check is only needed when we add collateral for someone else, so gas is not an issue
            # 2 * 10**(18 - borrow_decimals + collateral_decimals) =
            # = 2 * 10**18 * 10**(18 - borrow_decimals) / 10**(collateral_decimals)
            assert (
                d_collateral * staticcall ctrl.AMM.price_oracle()
                > 2
                * 10**18
                * ctrl.BORROWED_PRECISION // ctrl.COLLATERAL_PRECISION
            )
    ns: int256[2] = staticcall ctrl.AMM.read_user_tick_numbers(_for)
    size: uint256 = convert(unsafe_add(unsafe_sub(ns[1], ns[0]), 1), uint256)
    n1: int256 = ctrl._calculate_debt_n1(xy[1], debt, size, _for)
    n2: int256 = n1 + unsafe_sub(ns[1], ns[0])

    extcall ctrl.AMM.deposit_range(_for, xy[1], n1, n2)
    ctrl.loan[_for] = IController.Loan(initial_debt=debt, rate_mul=rate_mul)

    liquidation_discount: uint256 = 0
    if _for == msg.sender:
        liquidation_discount = ctrl.liquidation_discount
        ctrl.liquidation_discounts[_for] = liquidation_discount
    else:
        liquidation_discount = ctrl.liquidation_discounts[_for]

    if d_debt != 0:
        ctrl._total_debt.initial_debt = (
            ctrl._total_debt.initial_debt
            * rate_mul // ctrl._total_debt.rate_mul
            + d_debt
        )
        ctrl._total_debt.rate_mul = rate_mul

    if remove_collateral:
        log IController.RemoveCollateral(
            user=_for, collateral_decrease=d_collateral
        )
    else:
        log IController.Borrow(
            user=_for, collateral_increase=d_collateral, loan_increase=d_debt
        )

    log IController.UserState(
        user=_for,
        collateral=xy[1],
        debt=debt,
        n1=n1,
        n2=n2,
        liquidation_discount=liquidation_discount,
    )


@external
def add_collateral(collateral: uint256, _for: address = msg.sender):
    """
    @notice Add extra collateral to avoid bad liqidations
    @param collateral Amount of collateral to add
    @param _for Address to add collateral for
    """
    if collateral == 0:
        return
    self._add_collateral_borrow(collateral, 0, _for, False, _for != msg.sender)
    ctrl.transferFrom(
        ctrl.COLLATERAL_TOKEN, msg.sender, ctrl.AMM.address, collateral
    )
    ctrl._save_rate()


@external
def remove_collateral(collateral: uint256, _for: address = msg.sender):
    """
    @notice Remove some collateral without repaying the debt
    @param collateral Amount of collateral to remove
    @param _for Address to remove collateral for
    """
    if collateral == 0:
        return
    assert ctrl._check_approval(_for)
    self._add_collateral_borrow(collateral, 0, _for, True, False)
    ctrl.transferFrom(ctrl.COLLATERAL_TOKEN, ctrl.AMM.address, _for, collateral)
    ctrl._save_rate()


@external
def borrow_more(
    collateral: uint256,
    debt: uint256,
    _for: address = msg.sender,
    callbacker: address = empty(address),
    calldata: Bytes[10**4] = b"",
):
    """
    @notice Borrow more stablecoins while adding more collateral using a callback (to leverage more)
    @param collateral Amount of collateral to add
    @param debt Amount of stablecoin debt to take
    @param _for Address to borrow for
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    if debt == 0:
        return
    assert ctrl._check_approval(_for)

    more_collateral: uint256 = 0
    if callbacker != empty(address):
        ctrl.transfer(ctrl.BORROWED_TOKEN, callbacker, debt)
        # If there is any unused debt, callbacker can send it to the user
        more_collateral = ctrl.execute_callback(
            callbacker,
            ctrl.CALLBACK_DEPOSIT,
            _for,
            0,
            collateral,
            debt,
            calldata,
        ).collateral

    self._add_collateral_borrow(
        collateral + more_collateral, debt, _for, False, False
    )
    self.minted += debt

    ctrl.transferFrom(
        ctrl.COLLATERAL_TOKEN, msg.sender, ctrl.AMM.address, collateral
    )
    if more_collateral > 0:
        ctrl.transferFrom(
            ctrl.COLLATERAL_TOKEN, callbacker, ctrl.AMM.address, more_collateral
        )
    if callbacker == empty(address):
        ctrl.transfer(ctrl.BORROWED_TOKEN, _for, debt)
    ctrl._save_rate()


@external
def repay(
    _d_debt: uint256,
    _for: address = msg.sender,
    max_active_band: int256 = max_value(int256),
    callbacker: address = empty(address),
    calldata: Bytes[10**4] = b"",
):
    """
    @notice Repay debt (partially or fully)
    @param _d_debt The amount of debt to repay from user's wallet. If higher than the current debt - will do full repayment
    @param _for The user to repay the debt for
    @param max_active_band Don't allow active band to be higher than this (to prevent front-running the repay)
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = ctrl._debt(_for)
    assert debt > 0, "Loan doesn't exist"
    approval: bool = ctrl._check_approval(_for)
    xy: uint256[2] = empty(uint256[2])

    cb: IController.CallbackData = empty(IController.CallbackData)
    if callbacker != empty(address):
        assert approval
        xy = extcall ctrl.AMM.withdraw(_for, 10**18)
        ctrl.transferFrom(
            ctrl.COLLATERAL_TOKEN, ctrl.AMM.address, callbacker, xy[1]
        )
        cb = ctrl.execute_callback(
            callbacker, ctrl.CALLBACK_REPAY, _for, xy[0], xy[1], debt, calldata
        )

    total_stablecoins: uint256 = _d_debt + xy[0] + cb.stablecoins
    assert total_stablecoins > 0  # dev: no coins to repay
    d_debt: uint256 = 0

    # If we have more stablecoins than the debt - full repayment and closing the position
    if total_stablecoins >= debt:
        d_debt = debt
        debt = 0
        if callbacker == empty(address):
            xy = extcall ctrl.AMM.withdraw(_for, 10**18)

        if xy[0] > 0:
            # Only allow full repayment when underwater for the sender to do
            assert approval
            ctrl.transferFrom(
                ctrl.BORROWED_TOKEN, ctrl.AMM.address, self, xy[0]
            )
        if cb.stablecoins > 0:
            ctrl.transferFrom(
                ctrl.BORROWED_TOKEN, callbacker, self, cb.stablecoins
            )
        if _d_debt > 0:
            ctrl.transferFrom(ctrl.BORROWED_TOKEN, msg.sender, self, _d_debt)

        if total_stablecoins > d_debt:
            ctrl.transfer(
                ctrl.BORROWED_TOKEN, _for, unsafe_sub(total_stablecoins, d_debt)
            )
        # Transfer collateral to _for
        if callbacker == empty(address):
            if xy[1] > 0:
                ctrl.transferFrom(
                    ctrl.COLLATERAL_TOKEN, ctrl.AMM.address, _for, xy[1]
                )
        else:
            if cb.collateral > 0:
                ctrl.transferFrom(
                    ctrl.COLLATERAL_TOKEN, callbacker, _for, cb.collateral
                )
        ctrl._remove_from_list(_for)
        log IController.UserState(
            user=_for, collateral=0, debt=0, n1=0, n2=0, liquidation_discount=0
        )
        log IController.Repay(
            user=_for, collateral_decrease=xy[1], loan_decrease=d_debt
        )
    # Else - partial repayment
    else:
        active_band: int256 = staticcall ctrl.AMM.active_band_with_skip()
        assert active_band <= max_active_band

        d_debt = total_stablecoins
        debt = unsafe_sub(debt, d_debt)
        ns: int256[2] = staticcall ctrl.AMM.read_user_tick_numbers(_for)
        size: int256 = unsafe_sub(ns[1], ns[0])
        liquidation_discount: uint256 = ctrl.liquidation_discounts[_for]

        if ns[0] > active_band:
            # Not in soft-liquidation - can use callback and move bands
            new_collateral: uint256 = cb.collateral
            if callbacker == empty(address):
                xy = extcall ctrl.AMM.withdraw(_for, 10**18)
                new_collateral = xy[1]
            ns[0] = ctrl._calculate_debt_n1(
                new_collateral,
                debt,
                convert(unsafe_add(size, 1), uint256),
                _for,
            )
            ns[1] = ns[0] + size
            extcall ctrl.AMM.deposit_range(_for, new_collateral, ns[0], ns[1])
        else:
            # Underwater - cannot use callback or move bands but can avoid a bad liquidation
            xy = staticcall ctrl.AMM.get_sum_xy(_for)
            assert callbacker == empty(address)

        if approval:
            # Update liquidation discount only if we are that same user. No rugs
            liquidation_discount = ctrl.liquidation_discount
            ctrl.liquidation_discounts[_for] = liquidation_discount
        else:
            # Doesn't allow non-sender to repay in a way which ends with unhealthy state
            # full = False to make this condition non-manipulatable (and also cheaper on gas)
            assert ctrl._health(_for, debt, False, liquidation_discount) > 0

        if cb.stablecoins > 0:
            ctrl.transferFrom(
                ctrl.BORROWED_TOKEN, callbacker, self, cb.stablecoins
            )
        if _d_debt > 0:
            ctrl.transferFrom(ctrl.BORROWED_TOKEN, msg.sender, self, _d_debt)

        log IController.UserState(
            user=_for,
            collateral=xy[1],
            debt=debt,
            n1=ns[0],
            n2=ns[1],
            liquidation_discount=liquidation_discount,
        )
        log IController.Repay(
            user=_for, collateral_decrease=0, loan_decrease=d_debt
        )

    self.redeemed += d_debt

    ctrl.loan[_for] = IController.Loan(initial_debt=debt, rate_mul=rate_mul)
    total_debt: uint256 = (
        ctrl._total_debt.initial_debt * rate_mul // ctrl._total_debt.rate_mul
    )
    ctrl._total_debt.initial_debt = unsafe_sub(max(total_debt, d_debt), d_debt)
    ctrl._total_debt.rate_mul = rate_mul

    ctrl._save_rate()


@internal
def _liquidate(
    user: address,
    min_x: uint256,
    health_limit: uint256,
    frac: uint256,
    callbacker: address,
    calldata: Bytes[10**4],
):
    """
    @notice Perform a bad liquidation of user if the health is too bad
    @param user Address of the user
    @param min_x Minimal amount of stablecoin withdrawn (to avoid liquidators being sandwiched)
    @param health_limit Minimal health to liquidate at
    @param frac Fraction to liquidate; 100% = 10**18
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    debt: uint256 = 0
    rate_mul: uint256 = 0
    debt, rate_mul = ctrl._debt(user)

    if health_limit != 0:
        assert (
            ctrl._health(user, debt, True, health_limit) < 0
        ), "Not enough rekt"

    final_debt: uint256 = debt
    debt = unsafe_div(debt * frac + (10**18 - 1), 10**18)
    assert debt > 0
    final_debt = unsafe_sub(final_debt, debt)

    # Withdraw sender's stablecoin and collateral to our contract
    # When frac is set - we withdraw a bit less for the same debt fraction
    # f_remove = ((1 + h/2) / (1 + h) * (1 - frac) + frac) * frac
    # where h is health limit.
    # This is less than full h discount but more than no discount
    xy: uint256[2] = extcall ctrl.AMM.withdraw(
        user, ctrl._get_f_remove(frac, health_limit)
    )  # [stable, collateral]

    # x increase in same block -> price up -> good
    # x decrease in same block -> price down -> bad
    assert xy[0] >= min_x, "Slippage"

    min_amm_burn: uint256 = min(xy[0], debt)
    ctrl.transferFrom(ctrl.BORROWED_TOKEN, ctrl.AMM.address, self, min_amm_burn)

    if debt > xy[0]:
        to_repay: uint256 = unsafe_sub(debt, xy[0])

        if callbacker == empty(address):
            # Withdraw collateral if no callback is present
            ctrl.transferFrom(
                ctrl.COLLATERAL_TOKEN, ctrl.AMM.address, msg.sender, xy[1]
            )
            # Request what's left from user
            ctrl.transferFrom(ctrl.BORROWED_TOKEN, msg.sender, self, to_repay)

        else:
            # Move collateral to callbacker, call it and remove everything from it back in
            ctrl.transferFrom(
                ctrl.COLLATERAL_TOKEN, ctrl.AMM.address, callbacker, xy[1]
            )
            # Callback
            cb: IController.CallbackData = ctrl.execute_callback(
                callbacker,
                ctrl.CALLBACK_LIQUIDATE,
                user,
                xy[0],
                xy[1],
                debt,
                calldata,
            )
            assert cb.stablecoins >= to_repay, "not enough proceeds"
            if cb.stablecoins > to_repay:
                ctrl.transferFrom(
                    ctrl.BORROWED_TOKEN,
                    callbacker,
                    msg.sender,
                    unsafe_sub(cb.stablecoins, to_repay),
                )
            ctrl.transferFrom(ctrl.BORROWED_TOKEN, callbacker, self, to_repay)
            ctrl.transferFrom(
                ctrl.COLLATERAL_TOKEN, callbacker, msg.sender, cb.collateral
            )
    else:
        # Withdraw collateral
        ctrl.transferFrom(
            ctrl.COLLATERAL_TOKEN, ctrl.AMM.address, msg.sender, xy[1]
        )
        # Return what's left to user
        if xy[0] > debt:
            ctrl.transferFrom(
                ctrl.BORROWED_TOKEN,
                ctrl.AMM.address,
                msg.sender,
                unsafe_sub(xy[0], debt),
            )
    self.redeemed += debt
    ctrl.loan[user] = IController.Loan(
        initial_debt=final_debt, rate_mul=rate_mul
    )
    log IController.Repay(
        user=user, collateral_decrease=xy[1], loan_decrease=debt
    )
    log IController.Liquidate(
        liquidator=msg.sender,
        user=user,
        collateral_received=xy[1],
        stablecoin_received=xy[0],
        debt=debt,
    )
    if final_debt == 0:
        log IController.UserState(
            user=user, collateral=0, debt=0, n1=0, n2=0, liquidation_discount=0
        )  # Not logging partial removeal b/c we have not enough info
        ctrl._remove_from_list(user)

    d: uint256 = (
        ctrl._total_debt.initial_debt * rate_mul // ctrl._total_debt.rate_mul
    )
    ctrl._total_debt.initial_debt = unsafe_sub(max(d, debt), debt)
    ctrl._total_debt.rate_mul = rate_mul

    ctrl._save_rate()


@external
def liquidate(
    user: address,
    min_x: uint256,
    frac: uint256 = 10**18,
    callbacker: address = empty(address),
    calldata: Bytes[10**4] = b"",
):
    """
    @notice Perform a bad liquidation (or self-liquidation) of user if health is not good
    @param min_x Minimal amount of stablecoin to receive (to avoid liquidators being sandwiched)
    @param frac Fraction to liquidate; 100% = 10**18
    @param callbacker Address of the callback contract
    @param calldata Any data for callbacker
    """
    discount: uint256 = 0
    if not ctrl._check_approval(user):
        discount = ctrl.liquidation_discounts[user]
    self._liquidate(
        user, min_x, discount, min(frac, 10**18), callbacker, calldata
    )


@external
@reentrant
def set_amm_fee(fee: uint256):
    """
    @notice Set the AMM fee (factory admin only)
    @dev Reentrant because AMM is nonreentrant TODO check this one
    @param fee The fee which should be no higher than MAX_AMM_FEE
    """
    assert msg.sender == staticcall FACTORY.admin()
    assert fee <= ctrl.MAX_AMM_FEE and fee >= ctrl.MIN_AMM_FEE, "Fee"
    extcall ctrl.AMM.set_fee(fee)


@external
def set_monetary_policy(monetary_policy: address):
    """
    @notice Set monetary policy contract
    @param monetary_policy Address of the monetary policy contract
    """
    assert msg.sender == staticcall FACTORY.admin()
    ctrl._monetary_policy = IMonetaryPolicy(monetary_policy)
    extcall IMonetaryPolicy(monetary_policy).rate_write()
    log IController.SetMonetaryPolicy(monetary_policy=monetary_policy)


@external
def set_borrowing_discounts(
    loan_discount: uint256, liquidation_discount: uint256
):
    """
    @notice Set discounts at which we can borrow (defines max LTV) and where bad liquidation starts
    @param loan_discount Discount which defines LTV
    @param liquidation_discount Discount where bad liquidation starts
    """
    assert msg.sender == staticcall FACTORY.admin()
    assert loan_discount > liquidation_discount
    assert liquidation_discount >= ctrl.MIN_LIQUIDATION_DISCOUNT
    assert loan_discount <= ctrl.MAX_LOAN_DISCOUNT
    ctrl.liquidation_discount = liquidation_discount
    ctrl.loan_discount = loan_discount
    log IController.SetBorrowingDiscounts(
        loan_discount=loan_discount, liquidation_discount=liquidation_discount
    )


@external
def set_callback(cb: ILMGauge):
    """
    @notice Set liquidity mining callback
    """
    assert msg.sender == staticcall FACTORY.admin()
    extcall ctrl.AMM.set_callback(cb)
    log IController.SetLMCallback(callback=cb)


@external
@view
def admin_fees() -> uint256:
    """
    @notice Calculate the amount of fees obtained from the interest
    """
    minted: uint256 = self.minted
    return unsafe_sub(
        max(ctrl._get_total_debt() + self.redeemed, minted), minted
    )


@external
def collect_fees() -> uint256:
    """
    @notice Collect the fees charged as interest.
    """
    _to: address = staticcall FACTORY.fee_receiver()

    # Borrowing-based fees
    rate_mul: uint256 = staticcall ctrl.AMM.get_rate_mul()
    loan: IController.Loan = ctrl._total_debt
    loan.initial_debt = loan.initial_debt * rate_mul // loan.rate_mul
    loan.rate_mul = rate_mul
    ctrl._total_debt = loan

    ctrl._save_rate()

    # Amount which would have been redeemed if all the debt was repaid now
    to_be_redeemed: uint256 = loan.initial_debt + self.redeemed
    # Amount which was minted when borrowing + all previously claimed admin fees
    minted: uint256 = self.minted
    # Difference between to_be_redeemed and minted amount is exactly due to interest charged
    if to_be_redeemed > minted:
        self.minted = to_be_redeemed
        to_be_redeemed = unsafe_sub(
            to_be_redeemed, minted
        )  # Now this is the fees to charge
        ctrl.transfer(ctrl.BORROWED_TOKEN, _to, to_be_redeemed)
        log IController.CollectFees(
            amount=to_be_redeemed, new_supply=loan.initial_debt
        )
        return to_be_redeemed
    else:
        log IController.CollectFees(amount=0, new_supply=loan.initial_debt)
        return 0
