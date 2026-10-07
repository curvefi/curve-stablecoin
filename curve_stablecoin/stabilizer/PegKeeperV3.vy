# pragma version 0.4.3
"""
@title Peg Keeper V3
@author Curve.Fi
@license MIT
@notice Stabilizes crvUSD price in a 2-coin StableSwap pool by providing or withdrawing crvUSD
@dev Diff from PegKeeper V2:
    1. Pool imbalance is measured in rate-normalized units via `stored_rates()`,
       so yield-bearing / oraclized StableSwap-NG pools are supported.
       Legacy pools (no rate oracle) use constant rates derived from coin decimals.
    2. Profit is accounted in crvUSD: lp_balance * virtual_price - debt.
    3. Every provide / withdraw must earn at least a minimal profit relative to the moved amount
       (separate entry and exit thresholds), otherwise update() reverts. Caller's share is paid
       from the profit above that minimum.
    4. withdraw_profit() pays crvUSD from the idle balance and converts the paid amount into debt
       backed by LP tokens, instead of transferring surplus LP tokens.
    5. Debt ceiling cuts are applied the way FastBridgeVault does: anyone can schedule_rug(), idle
       crvUSD is returned to the factory before being used, and provide / withdraw_profit are
       blocked until the cut is fully honored.
    6. Donated paired coin is deposited into the pool: 50/50 by value with idle crvUSD while crvUSD
       is scarce (subject to provide_allowed()), paired coin only while crvUSD is abundant (subject to
       withdraw_allowed()). LP minted above the crvUSD part is Peg Keeper's profit.
@custom:kill Regulator can ban provide and / or withdraw via provide_allowed() / withdraw_allowed().
    Owner can switch the regulator (e.g. to PegKeeperOffboarding to leave only withdrawals).
    Factory can always pull idle crvUSD back by cutting the debt ceiling; with the ceiling at 0 the
    keeper can only withdraw, and owner can move all LP tokens and paired coin out via offload()
    to unwind them elsewhere (e.g. paired coin depeg); debt is reset and the hole is tracked by the
    factory as debt_ceiling_residual until crvUSD is returned to the keeper and burned via rug.
    Once the hole is closed, owner can move crvUSD above what the factory minted out via
    recover_excess().
@custom:security Pool is trusted (Curve StableSwap). Regulator is trusted and set by owner.
    Caller reward is paid in LP tokens valued at the pool virtual price.
    Ownership is two-step (snekmate ownable_2step); renounce_ownership is not exported.
@custom:version 3.0.0
"""

from snekmate.auth import ownable
from snekmate.auth import ownable_2step

initializes: ownable
initializes: ownable_2step[ownable := ownable]
exports: (
    ownable_2step.owner,
    ownable_2step.pending_owner,
    ownable_2step.transfer_ownership,
    ownable_2step.accept_ownership,
)


interface Regulator:
    def stablecoin() -> address: view
    def provide_allowed(_pk: address = msg.sender) -> uint256: view
    def withdraw_allowed(_pk: address = msg.sender) -> uint256: view
    def fee_receiver() -> address: view


interface CurvePool:
    def balances(_i: uint256) -> uint256: view
    def coins(_i: uint256) -> address: view
    def stored_rates() -> DynArray[uint256, MAX_COINS]: view
    def get_virtual_price() -> uint256: view
    def balanceOf(_owner: address) -> uint256: view
    def transfer(_to: address, _value: uint256) -> bool: nonpayable


interface CurvePoolOld:
    def calc_token_amount(_amounts: uint256[2], _is_deposit: bool) -> uint256: view
    def add_liquidity(_amounts: uint256[2], _min_mint_amount: uint256) -> uint256: nonpayable
    def remove_liquidity_imbalance(
        _amounts: uint256[2], _max_burn_amount: uint256
    ) -> uint256: nonpayable


interface CurvePoolNG:
    def calc_token_amount(
        _amounts: DynArray[uint256, MAX_COINS], _is_deposit: bool
    ) -> uint256: view
    def add_liquidity(
        _amounts: DynArray[uint256, MAX_COINS], _min_mint_amount: uint256
    ) -> uint256: nonpayable
    def remove_liquidity_imbalance(
        _amounts: DynArray[uint256, MAX_COINS], _max_burn_amount: uint256
    ) -> uint256: nonpayable


interface Factory:  # ControllerFactory
    def rug_debt_ceiling(_to: address): nonpayable
    def debt_ceiling(_of: address) -> uint256: view
    def debt_ceiling_residual(_of: address) -> uint256: view


interface ERC20:
    def approve(_spender: address, _amount: uint256): nonpayable
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_owner: address) -> uint256: view
    def decimals() -> uint256: view


event Provide:
    amount: uint256


event Withdraw:
    amount: uint256


event Profit:
    amount: uint256


event SetNewActionDelay:
    action_delay: uint256


event SetNewCallerShare:
    caller_share: uint256


event SetNewMinProfit:
    provide_min_profit: uint256
    withdraw_min_profit: uint256


event SetNewRegulator:
    regulator: address


event RugScheduled:
    status: bool


event DepositDonation:
    paired_amount: uint256
    pegged_amount: uint256
    lp_amount: uint256


event Offload:
    receiver: indexed(address)
    lp_amount: uint256
    paired_amount: uint256
    debt: uint256


event RecoverExcess:
    receiver: indexed(address)
    amount: uint256


struct BalanceDiff:
    amount: uint256  # imbalance in units of pegged coin
    deficit: bool  # True if pegged coin is scarce in the pool


PRECISION: constant(uint256) = 10**18
MAX_COINS: constant(uint256) = 8
MAX_DONATION_LOSS: constant(uint256) = 10**14  # 1bp of deposited value

# Pool
POOL: immutable(CurvePool)
I: immutable(uint256)  # index of pegged in pool
PEGGED: immutable(ERC20)
PAIRED: immutable(ERC20)  # the second coin of the pool
IS_INVERSE: public(immutable(bool))
IS_NG: public(immutable(bool))  # Interface for CurveStableSwapNG
RATES: immutable(uint256[2])  # Constant rates for legacy pools: 10 ** (36 - decimals)
FACTORY: immutable(Factory)

# Accounting
regulator: public(Regulator)
action_delay: public(uint256)  # Time between providing / withdrawing coins
last_change: public(uint256)
debt: public(uint256)  # crvUSD provided into the pool and not yet withdrawn
rug_scheduled: public(bool)  # Debt ceiling was cut and idle crvUSD must be returned to factory

# Profit
SHARE_PRECISION: constant(uint256) = 10**5  # 100% = 10 ** 5
MAX_MIN_PROFIT: constant(uint256) = PRECISION // 100  # 1% of the moved amount
caller_share: public(uint256)
provide_min_profit: public(uint256)  # min profit per provided crvUSD, with PRECISION
withdraw_min_profit: public(uint256)  # min profit per withdrawn crvUSD, with PRECISION


@deploy
def __init__(
    _pool: CurvePool,
    _caller_share: uint256,
    _provide_min_profit: uint256,
    _withdraw_min_profit: uint256,
    _factory: Factory,
    _regulator: Regulator,
    _owner: address,
):
    """
    @notice Contract constructor
    @param _pool StableSwap pool with 2 coins, one of them is the stablecoin being pegged
    @param _caller_share Caller's share of profit, with SHARE_PRECISION
    @param _provide_min_profit Min profit per provided crvUSD, with PRECISION
    @param _withdraw_min_profit Min profit per withdrawn crvUSD, with PRECISION
    @param _factory Factory which should be able to take coins away
    @param _regulator Peg Keeper Regulator
    @param _owner Owner account
    """
    assert _factory.address != empty(address)  # dev: bad factory
    assert _regulator.address != empty(address)  # dev: bad regulator
    assert _owner != empty(address)  # dev: bad owner

    POOL = _pool
    FACTORY = _factory
    pegged: ERC20 = ERC20(staticcall _regulator.stablecoin())
    PEGGED = pegged
    extcall pegged.approve(_pool.address, max_value(uint256))
    # Allow factory to rug debt ceiling
    extcall pegged.approve(_factory.address, max_value(uint256))

    coins: ERC20[2] = [ERC20(staticcall _pool.coins(0)), ERC20(staticcall _pool.coins(1))]
    assert pegged in coins  # dev: pegged not in pool
    i: uint256 = 1
    if coins[0] == pegged:
        i = 0
    I = i
    IS_INVERSE = i == 0
    PAIRED = coins[1 - i]
    extcall coins[1 - i].approve(_pool.address, max_value(uint256))  # for donations
    RATES = [
        10**(36 - staticcall coins[0].decimals()),
        10**(36 - staticcall coins[1].decimals()),
    ]

    IS_NG = raw_call(
        _pool.address,
        abi_encode(convert(0, uint256), method_id=method_id("price_oracle(uint256)")),
        revert_on_failure=False,
    )
    if IS_NG:
        assert len(staticcall _pool.stored_rates()) == 2  # dev: not a 2-coin pool

    ownable.__init__()
    ownable_2step.__init__()
    ownable._transfer_ownership(_owner)

    self.regulator = _regulator
    log SetNewRegulator(regulator=_regulator.address)

    assert _caller_share <= SHARE_PRECISION  # dev: bad part value
    self.caller_share = _caller_share
    log SetNewCallerShare(caller_share=_caller_share)

    assert _provide_min_profit <= MAX_MIN_PROFIT  # dev: bad min profit
    assert _withdraw_min_profit <= MAX_MIN_PROFIT  # dev: bad min profit
    self.provide_min_profit = _provide_min_profit
    self.withdraw_min_profit = _withdraw_min_profit
    log SetNewMinProfit(
        provide_min_profit=_provide_min_profit, withdraw_min_profit=_withdraw_min_profit
    )

    self.action_delay = 12  # 1 block
    log SetNewActionDelay(action_delay=12)


@external
@view
def factory() -> address:
    return FACTORY.address


@external
@view
def pegged() -> address:
    """
    @return Address of stablecoin being pegged
    """
    return PEGGED.address


@external
@view
def pool() -> CurvePool:
    """
    @return StableSwap pool being used
    """
    return POOL


# ------------------------------ Profit accounting -----------------------------


@internal
@pure
def _calc_profit_from(_lp_balance: uint256, _virtual_price: uint256, _debt: uint256) -> uint256:
    """
    @notice PegKeeper's profit formula in crvUSD
    @dev LP value is rounded down, so profit is conservative
    """
    lp_value: uint256 = _lp_balance * _virtual_price // PRECISION
    if lp_value <= _debt:
        return 0
    return lp_value - _debt


@internal
@view
def _calc_profit() -> uint256:
    """
    @notice Calculate PegKeeper's profit using current values
    """
    return self._calc_profit_from(
        staticcall POOL.balanceOf(self), staticcall POOL.get_virtual_price(), self.debt
    )


@internal
@view
def _min_profit(_amount: uint256, _deficit: bool) -> uint256:
    """
    @notice Min profit required for moving _amount: entry (provide) or exit (withdraw) threshold
    @dev Rounded down
    """
    min_profit: uint256 = self.provide_min_profit if _deficit else self.withdraw_min_profit
    return _amount * min_profit // PRECISION


@external
@view
def calc_profit() -> uint256:
    """
    @notice Calculate generated profit in crvUSD. Does NOT include already withdrawn profit
    @return Amount of generated profit
    """
    return self._calc_profit()


# -------------------------------- Debt ceiling ---------------------------------


@internal
@view
def _need_to_rug() -> bool:
    """
    @notice Check if there was a cut in debt ceiling
    """
    return staticcall FACTORY.debt_ceiling_residual(self) > staticcall FACTORY.debt_ceiling(self)


@internal
@view
def _calc_balance() -> uint256:
    """
    @notice Idle crvUSD balance left after the scheduled debt ceiling cut is applied
    @return 0 while the cut can not be fully honored
    """
    balance: uint256 = staticcall PEGGED.balanceOf(self)
    if self.rug_scheduled:
        residual: uint256 = staticcall FACTORY.debt_ceiling_residual(self)
        to_rug: uint256 = residual - min(residual, staticcall FACTORY.debt_ceiling(self))
        if to_rug >= balance:
            return 0
        balance -= to_rug
    return balance


@internal
def _get_balance(_rug: bool = False) -> uint256:
    """
    @notice Get idle crvUSD balance after rugging debt ceiling
    @param _rug Rug even if not scheduled yet
    @return Amount of crvUSD available to use, 0 while the cut can not be fully honored
    """
    if self.rug_scheduled or _rug:
        extcall FACTORY.rug_debt_ceiling(self)
        rug_scheduled: bool = self._need_to_rug()
        if rug_scheduled != self.rug_scheduled:
            self.rug_scheduled = rug_scheduled
            log RugScheduled(status=rug_scheduled)
        if rug_scheduled:
            return 0
    return staticcall PEGGED.balanceOf(self)


@external
def schedule_rug() -> bool:
    """
    @notice Rug debt ceiling and keep rugging if the cut is not fully honored yet. Callable by anyone
    @return Boolean whether need to rug or not
    """
    self._get_balance(True)
    return self.rug_scheduled


# ------------------------------------- Pool ------------------------------------


@internal
@view
def _rates() -> uint256[2]:
    """
    @notice Rates to normalize pool balances to 18 decimals: `stored_rates()` for NG pools
        (includes rate oracle), constant for legacy pools
    """
    if IS_NG:
        rates: DynArray[uint256, MAX_COINS] = staticcall POOL.stored_rates()
        return [rates[0], rates[1]]
    return RATES


@internal
@view
def _calc_token_amount(_amounts: uint256[2], _is_deposit: bool) -> uint256:
    if IS_NG:
        return staticcall CurvePoolNG(POOL.address).calc_token_amount(
            [_amounts[0], _amounts[1]], _is_deposit
        )
    return staticcall CurvePoolOld(POOL.address).calc_token_amount(_amounts, _is_deposit)


@internal
def _add_liquidity(_amounts: uint256[2], _min_mint_amount: uint256) -> uint256:
    if IS_NG:
        return extcall CurvePoolNG(POOL.address).add_liquidity(
            [_amounts[0], _amounts[1]], _min_mint_amount
        )
    return extcall CurvePoolOld(POOL.address).add_liquidity(_amounts, _min_mint_amount)


@internal
def _remove_liquidity_imbalance(_amount: uint256):
    if IS_NG:
        amounts: DynArray[uint256, 2] = [0, 0]
        amounts[I] = _amount
        extcall CurvePoolNG(POOL.address).remove_liquidity_imbalance(amounts, max_value(uint256))
    else:
        amounts: uint256[2] = empty(uint256[2])
        amounts[I] = _amount
        extcall CurvePoolOld(POOL.address).remove_liquidity_imbalance(amounts, max_value(uint256))


# ------------------------------------ Update -----------------------------------


@internal
@view
def _balance_diff() -> BalanceDiff:
    """
    @notice Pool imbalance measured in rate-normalized units (supports yield-bearing coins)
    @dev Returned in raw units of the pegged coin because PK always moves coin I.
        Rounded down so we never try to move more value than the observed imbalance.
    """
    rates: uint256[2] = self._rates()
    normalized_pegged: uint256 = staticcall POOL.balances(I) * rates[I] // PRECISION
    normalized_paired: uint256 = staticcall POOL.balances(1 - I) * rates[1 - I] // PRECISION

    if normalized_pegged >= normalized_paired:
        return BalanceDiff(
            amount=unsafe_sub(normalized_pegged, normalized_paired) * PRECISION // rates[I],
            deficit=False,
        )
    return BalanceDiff(
        amount=unsafe_sub(normalized_paired, normalized_pegged) * PRECISION // rates[I],
        deficit=True,
    )


@internal
@view
def _allowed(_deficit: bool) -> uint256:
    """
    @notice Amount of crvUSD the regulator allows to provide (deficit) or withdraw
    """
    if _deficit:
        return staticcall self.regulator.provide_allowed()
    return staticcall self.regulator.withdraw_allowed()


@internal
@view
def _calc_call_profit(_amount: uint256, _deficit: bool) -> uint256:
    """
    @notice Calculate profit in crvUSD from calling update() above the min profit threshold
    @dev Returns 0 if the min profit threshold is not met
    """
    lp_balance: uint256 = staticcall POOL.balanceOf(self)
    virtual_price: uint256 = staticcall POOL.get_virtual_price()
    debt: uint256 = self.debt
    initial_profit: uint256 = self._calc_profit_from(lp_balance, virtual_price, debt)

    amount: uint256 = 0
    if _deficit:
        amount = min(_amount, self._calc_balance())
    else:
        amount = min(_amount, debt)

    amounts: uint256[2] = empty(uint256[2])
    amounts[I] = amount
    lp_balance_diff: uint256 = self._calc_token_amount(amounts, _deficit)

    if _deficit:
        lp_balance += lp_balance_diff
        debt += amount
    else:
        if lp_balance_diff > lp_balance:
            return 0  # not enough LP to withdraw, update() would revert
        lp_balance -= lp_balance_diff
        debt -= amount

    new_profit: uint256 = self._calc_profit_from(lp_balance, virtual_price, debt)
    if new_profit <= initial_profit:
        return 0
    profit: uint256 = new_profit - initial_profit
    min_profit: uint256 = self._min_profit(amount, _deficit)
    if profit < min_profit:
        return 0
    return profit - min_profit


@external
@view
def estimate_caller_profit() -> uint256:
    """
    @notice Estimate profit from calling update()
    @dev This method is not precise, real profit is always more because of increasing virtual price
    @return Expected amount of profit in crvUSD going to beneficiary
    """
    if self.last_change + self.action_delay > block.timestamp:
        return 0

    diff: BalanceDiff = self._balance_diff()
    amount: uint256 = min(diff.amount // 5, self._allowed(diff.deficit))
    return self._calc_call_profit(amount, diff.deficit) * self.caller_share // SHARE_PRECISION


@internal
def _provide(_amount: uint256) -> uint256:
    """
    @notice Implementation of provide
    @dev Coins should be already in the contract
    @return Amount of crvUSD provided
    """
    amount: uint256 = min(_amount, self._get_balance())
    if amount == 0:
        return 0

    amounts: uint256[2] = empty(uint256[2])
    amounts[I] = amount
    self._add_liquidity(amounts, 0)

    self.last_change = block.timestamp
    self.debt += amount
    log Provide(amount=amount)
    return amount


@internal
def _withdraw(_amount: uint256) -> uint256:
    """
    @notice Implementation of withdraw
    @return Amount of crvUSD withdrawn
    """
    debt: uint256 = self.debt
    amount: uint256 = min(_amount, debt)
    if amount == 0:
        return 0

    self._remove_liquidity_imbalance(amount)

    self.last_change = block.timestamp
    self.debt = debt - amount
    log Withdraw(amount=amount)
    return amount


@external
@nonreentrant
def update(_beneficiary: address = msg.sender) -> uint256:
    """
    @notice Provide or withdraw coins from the pool to stabilize it
    @dev Reverts if the action is unprofitable or profit per moved crvUSD is below threshold.
        Beneficiary gets caller_share of the profit above the threshold
    @param _beneficiary Beneficiary address
    @return Profit in crvUSD received by beneficiary (paid in LP tokens at virtual price)
    """
    if self.last_change + self.action_delay > block.timestamp:
        return 0

    diff: BalanceDiff = self._balance_diff()
    initial_profit: uint256 = self._calc_profit()

    allowed: uint256 = self._allowed(diff.deficit)
    assert allowed > 0, "Regulator ban"
    amount: uint256 = min(diff.amount // 5, allowed)
    if diff.deficit:
        amount = self._provide(amount)  # this dumps stablecoin
    else:
        amount = self._withdraw(amount)  # this pumps stablecoin

    new_profit: uint256 = self._calc_profit()
    assert new_profit > initial_profit, "peg unprofitable"
    profit: uint256 = new_profit - initial_profit
    min_profit: uint256 = self._min_profit(amount, diff.deficit)
    assert profit >= min_profit, "profit below min"

    # Send caller's share of profit above the min
    caller_profit: uint256 = (profit - min_profit) * self.caller_share // SHARE_PRECISION
    if caller_profit > 0:
        lp_amount: uint256 = caller_profit * PRECISION // staticcall POOL.get_virtual_price()
        assert extcall POOL.transfer(_beneficiary, lp_amount)

    return caller_profit


# ---------------------------------- Donations ----------------------------------


@internal
def _deposit_donation() -> uint256:
    """
    @notice Deposit donated paired coin into the pool.
        crvUSD scarce: 50/50 by value with idle crvUSD (crvUSD part is debt).
        crvUSD abundant: paired coin only, up to 1/5 of the imbalance per call, no debt.
        Silently does nothing if there is nothing to deposit, the regulator does not allow the
        direction, or the pool would mint less than MAX_DONATION_LOSS tolerates
    @dev Both branches move the pool towards balance and earn the scarce coin premium;
        the loss in a balanced pool is bounded by fee / 2 on the deposit
    @return Amount of LP tokens minted
    """
    paired: uint256 = staticcall PAIRED.balanceOf(self)
    if paired == 0:
        return 0

    rates: uint256[2] = self._rates()
    diff: BalanceDiff = self._balance_diff()
    allowed: uint256 = self._allowed(diff.deficit)
    pegged: uint256 = 0
    if diff.deficit:
        # crvUSD is scarce: 50/50 by value, crvUSD part is a provide
        pegged = min(paired * rates[1 - I] // rates[I], self._get_balance())
        pegged = min(pegged, allowed)
        if pegged == 0:
            return 0
        paired = pegged * rates[I] // rates[1 - I]
    else:
        # crvUSD is abundant: paired coin only, like a withdraw for the pool price
        if allowed == 0:
            return 0
        paired = min(paired, diff.amount // 5 * rates[I] // rates[1 - I])
        if paired == 0:
            return 0
    amounts: uint256[2] = empty(uint256[2])
    amounts[I] = pegged
    amounts[1 - I] = paired
    value: uint256 = pegged + paired * rates[1 - I] // rates[I]
    min_mint_amount: uint256 = (
        value * (PRECISION - MAX_DONATION_LOSS) // staticcall POOL.get_virtual_price()
    )
    if self._calc_token_amount(amounts, True) < min_mint_amount:
        return 0

    lp_amount: uint256 = self._add_liquidity(amounts, min_mint_amount)
    self.debt += pegged
    log DepositDonation(paired_amount=paired, pegged_amount=pegged, lp_amount=lp_amount)
    return lp_amount


@external
@nonreentrant
def deposit_donation() -> uint256:
    """
    @notice Deposit donated paired coin into the pool. Callable by anyone
    @return Amount of LP tokens minted, 0 if nothing was deposited
    """
    return self._deposit_donation()


# ------------------------------- Withdraw profit -------------------------------


@external
@nonreentrant
def withdraw_profit(_deposit_donation: bool = True) -> uint256:
    """
    @notice Withdraw profit generated by Peg Keeper in crvUSD
    @dev Profit is paid from the idle crvUSD balance and the same amount is added to debt,
        so LP tokens keep backing the whole debt and (debt + idle balance) does not change.
        Limited by the idle balance; the rest can be withdrawn after the next withdraw.
        Scheduled debt ceiling cut is applied first.
    @param _deposit_donation Deposit donated paired coin first (skipped silently if not possible)
    @return Amount of crvUSD sent to fee receiver
    """
    if _deposit_donation:
        self._deposit_donation()

    amount: uint256 = min(self._calc_profit(), self._get_balance())
    if amount == 0:
        return 0

    self.debt += amount
    assert extcall PEGGED.transfer(
        staticcall self.regulator.fee_receiver(), amount, default_return_value=True
    )

    log Profit(amount=amount)
    return amount


# ----------------------------------- Offload -----------------------------------


@external
@nonreentrant
def offload(_receiver: address) -> uint256:
    """
    @notice Move all LP tokens and not yet deposited paired coin out to unwind them elsewhere,
        e.g. when the paired coin is depegged and withdrawing crvUSD from the pool is not an
        option. Only transfers, does not swap. Only after the DAO has cut the debt ceiling to 0,
        i.e. decommissioned this keeper
    @dev debt is reset: the hole is tracked by the factory as debt_ceiling_residual until crvUSD
        is sent back to the keeper and burned via rug, which is kept scheduled so crvUSD sent back
        can not be provided again
    @param _receiver Receiver of LP tokens and paired coin
    @return Amount of LP tokens transferred
    """
    ownable._check_owner()
    assert staticcall FACTORY.debt_ceiling(self) == 0  # dev: debt ceiling is not zero
    assert _receiver != empty(address)  # dev: bad receiver
    self._get_balance(True)  # burn idle crvUSD now, keep rugging returns while the hole is open

    debt: uint256 = self.debt
    self.debt = 0
    lp_amount: uint256 = staticcall POOL.balanceOf(self)
    assert extcall POOL.transfer(_receiver, lp_amount)
    paired_amount: uint256 = staticcall PAIRED.balanceOf(self)
    if paired_amount > 0:
        assert extcall PAIRED.transfer(_receiver, paired_amount, default_return_value=True)
    log Offload(receiver=_receiver, lp_amount=lp_amount, paired_amount=paired_amount, debt=debt)
    return lp_amount


@external
@nonreentrant
def recover_excess(_receiver: address) -> uint256:
    """
    @notice Move out crvUSD held above what the factory minted (donations, offloaded LP proceeds
        above the hole). Only after the DAO has cut the debt ceiling to 0: the rug burns idle
        crvUSD up to the residual first, whatever is left is the excess
    @param _receiver Receiver of crvUSD
    @return Amount of crvUSD transferred, 0 while the residual is not covered yet
    """
    ownable._check_owner()
    assert staticcall FACTORY.debt_ceiling(self) == 0  # dev: debt ceiling is not zero
    assert _receiver != empty(address)  # dev: bad receiver

    amount: uint256 = self._get_balance(True)  # 0 while the factory still has crvUSD to burn
    if amount > 0:
        assert extcall PEGGED.transfer(_receiver, amount, default_return_value=True)
        log RecoverExcess(receiver=_receiver, amount=amount)
    return amount


# ------------------------------- Owner methods --------------------------------


@external
def set_new_action_delay(_new_action_delay: uint256):
    """
    @notice Set new action delay
    @param _new_action_delay Action delay in seconds
    """
    ownable._check_owner()

    self.action_delay = _new_action_delay

    log SetNewActionDelay(action_delay=_new_action_delay)


@external
def set_new_caller_share(_new_caller_share: uint256):
    """
    @notice Set new update caller's part
    @param _new_caller_share Part with SHARE_PRECISION
    """
    ownable._check_owner()
    assert _new_caller_share <= SHARE_PRECISION  # dev: bad part value

    self.caller_share = _new_caller_share

    log SetNewCallerShare(caller_share=_new_caller_share)


@external
def set_new_min_profit(_provide_min_profit: uint256, _withdraw_min_profit: uint256):
    """
    @notice Set new entry / exit profit thresholds
    @param _provide_min_profit Min profit per provided crvUSD, with PRECISION
    @param _withdraw_min_profit Min profit per withdrawn crvUSD, with PRECISION
    """
    ownable._check_owner()
    assert _provide_min_profit <= MAX_MIN_PROFIT  # dev: bad min profit
    assert _withdraw_min_profit <= MAX_MIN_PROFIT  # dev: bad min profit

    self.provide_min_profit = _provide_min_profit
    self.withdraw_min_profit = _withdraw_min_profit

    log SetNewMinProfit(
        provide_min_profit=_provide_min_profit, withdraw_min_profit=_withdraw_min_profit
    )


@external
def set_new_regulator(_new_regulator: Regulator):
    """
    @notice Set new peg keeper regulator
    """
    ownable._check_owner()
    assert _new_regulator.address != empty(address)  # dev: bad regulator

    self.regulator = _new_regulator
    log SetNewRegulator(regulator=_new_regulator.address)
