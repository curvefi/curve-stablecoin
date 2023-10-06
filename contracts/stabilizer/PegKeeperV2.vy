# @version 0.3.9
"""
@title Peg Keeper V2
@license MIT
@author Curve.Fi
@notice Peg Keeper
@dev Version 2
"""

interface Regulator:
    def stablecoin() -> address: view
    def provide_allowed(_pk: address=msg.sender) -> bool: view
    def withdraw_allowed(_pk: address=msg.sender) -> bool: view

interface CurvePool:
    def balances(i_coin: uint256) -> uint256: view
    def coins(i: uint256) -> address: view
    def calc_token_amount(_amounts: uint256[2], _is_deposit: bool) -> uint256: view
    def add_liquidity(_amounts: uint256[2], _min_mint_amount: uint256) -> uint256: nonpayable
    def remove_liquidity_imbalance(_amounts: uint256[2], _max_burn_amount: uint256) -> uint256: nonpayable
    def get_virtual_price() -> uint256: view
    def balanceOf(arg0: address) -> uint256: view
    def transfer(_to: address, _value: uint256) -> bool: nonpayable

interface ERC20:
    def approve(_spender: address, _amount: uint256): nonpayable
    def decimals() -> uint256: view


event Provide:
    amount: uint256

event Withdraw:
    amount: uint256

event Profit:
    lp_amount: uint256

event CommitNewReceiver:
    receiver: address

event ApplyNewReceiver:
    receiver: address

event CommitNewAdmin:
    admin: address

event ApplyNewAdmin:
    admin: address

event SetNewCallerShare:
    caller_share: uint256

event SetNewRegulator:
    regulator: address


# Time between providing/withdrawing coins
ACTION_DELAY: constant(uint256) = 15 * 60
ADMIN_ACTIONS_DELAY: constant(uint256) = 3 * 86400

PRECISION: constant(uint256) = 10 ** 18
# Calculation error for profit
PROFIT_THRESHOLD: constant(uint256) = 10 ** 18

POOL: immutable(CurvePool)
I: immutable(uint256)  # index of pegged in pool
PEGGED: immutable(ERC20)
IS_INVERSE: immutable(bool)
PEG_MUL: immutable(uint256)

regulator: public(Regulator)

last_change: public(uint256)
debt: public(uint256)

SHARE_PRECISION: constant(uint256) = 10 ** 5
caller_share: public(uint256)

admin: public(address)
future_admin: public(address)

# Receiver of profit
receiver: public(address)
future_receiver: public(address)

new_admin_deadline: public(uint256)
new_receiver_deadline: public(uint256)

FACTORY: immutable(address)


@external
def __init__(
    _pool: CurvePool, _receiver: address, _caller_share: uint256,
    _factory: address, _regulator: Regulator, _admin: address,
):
    """
    @notice Contract constructor
    @param _pool Contract pool address
    @param _receiver Receiver of the profit
    @param _caller_share Caller's share of profit
    @param _factory Factory which should be able to take coins away
    @param _regulator Peg Keeper Regulator
    @param _admin Admin account
    """
    POOL = _pool
    pegged: ERC20 = ERC20(_regulator.stablecoin())
    PEGGED = pegged
    pegged.approve(_pool.address, max_value(uint256))
    pegged.approve(_factory, max_value(uint256))

    coins: ERC20[2] = [ERC20(_pool.coins(0)), ERC20(_pool.coins(1))]
    for i in range(2):
        if coins[i] == pegged:
            I = i
            IS_INVERSE = (i == 0)
        else:
            PEG_MUL = 10 ** (18 - coins[i].decimals())

    self.admin = _admin
    log ApplyNewAdmin(msg.sender)

    assert _receiver != empty(address)
    self.receiver = _receiver
    log ApplyNewReceiver(_receiver)

    self.regulator = _regulator
    log SetNewRegulator(_regulator.address)

    assert _caller_share <= SHARE_PRECISION  # dev: bad part value
    self.caller_share = _caller_share
    log SetNewCallerShare(_caller_share)

    FACTORY = _factory


@pure
@external
def factory() -> address:
    return FACTORY


@pure
@external
def pegged() -> address:
    return PEGGED.address


@pure
@external
def pool() -> CurvePool:
    return POOL


@internal
def _provide(_amount: uint256):
    # We already have all reserves here
    # ERC20(PEGGED).mint(self, _amount)
    if _amount == 0:
        return

    amounts: uint256[2] = empty(uint256[2])
    amounts[I] = _amount
    POOL.add_liquidity(amounts, 0)

    self.last_change = block.timestamp
    self.debt += _amount
    log Provide(_amount)


@internal
def _withdraw(_amount: uint256):
    if _amount == 0:
        return

    debt: uint256 = self.debt
    amount: uint256 = min(_amount, debt)

    amounts: uint256[2] = empty(uint256[2])
    amounts[I] = amount
    POOL.remove_liquidity_imbalance(amounts, max_value(uint256))

    self.last_change = block.timestamp
    self.debt -= amount

    log Withdraw(amount)


@internal
@view
def _calc_profit() -> uint256:
    lp_balance: uint256 = POOL.balanceOf(self)

    virtual_price: uint256 = POOL.get_virtual_price()
    lp_debt: uint256 = self.debt * PRECISION / virtual_price + PROFIT_THRESHOLD

    if lp_balance <= lp_debt:
        return 0
    else:
        return lp_balance - lp_debt


@internal
@view
def _calc_future_profit(_amount: uint256, _is_deposit: bool) -> uint256:
    lp_balance: uint256 = POOL.balanceOf(self)
    debt: uint256 = self.debt
    amount: uint256 = _amount
    if not _is_deposit:
        amount = min(_amount, debt)

    amounts: uint256[2] = empty(uint256[2])
    amounts[I] = amount
    lp_balance_diff: uint256 = POOL.calc_token_amount(amounts, _is_deposit)

    if _is_deposit:
        lp_balance += lp_balance_diff
        debt += amount
    else:
        lp_balance -= lp_balance_diff
        debt -= amount

    virtual_price: uint256 = POOL.get_virtual_price()
    lp_debt: uint256 = debt * PRECISION / virtual_price + PROFIT_THRESHOLD

    if lp_balance <= lp_debt:
        return 0
    else:
        return lp_balance - lp_debt


@external
@view
def calc_profit() -> uint256:
    """
    @notice Calculate generated profit in LP tokens
    @return Amount of generated profit
    """
    return self._calc_profit()


@external
@view
def estimate_caller_profit() -> uint256:
    """
    @notice Estimate profit from calling update()
    @dev This method is not precise, real profit is always more because of increasing virtual price
    @return Expected amount of profit going to beneficiary
    """
    if self.last_change + ACTION_DELAY > block.timestamp:
        return 0

    balance_pegged: uint256 = POOL.balances(I)
    balance_peg: uint256 = POOL.balances(1 - I) * PEG_MUL

    initial_profit: uint256 = self._calc_profit()

    # Checking the balance will ensure no-loss of the stabilizer, but to ensure stabilization
    # we need to exclude "bad" p_agg, so we add an extra check for it

    new_profit: uint256 = 0
    if balance_peg > balance_pegged:
        if not self.regulator.provide_allowed():
            return 0
        new_profit = self._calc_future_profit((balance_peg - balance_pegged) / 5, True)  # this dumps stablecoin

    else:
        if not self.regulator.withdraw_allowed():
            return 0
        new_profit = self._calc_future_profit((balance_pegged - balance_peg) / 5, False)  # this pumps stablecoin

    if new_profit < initial_profit:
        return 0
    lp_amount: uint256 = new_profit - initial_profit

    return lp_amount * self.caller_share / SHARE_PRECISION


@external
@nonpayable
def update(_beneficiary: address = msg.sender) -> uint256:
    """
    @notice Provide or withdraw coins from the pool to stabilize it
    @param _beneficiary Beneficiary address
    @return Amount of profit received by beneficiary
    """
    if self.last_change + ACTION_DELAY > block.timestamp:
        return 0

    balance_pegged: uint256 = POOL.balances(I)
    balance_peg: uint256 = POOL.balances(1 - I) * PEG_MUL

    initial_profit: uint256 = self._calc_profit()

    if balance_peg > balance_pegged:
        assert self.regulator.provide_allowed(), "Regulator ban"
        self._provide(unsafe_sub(balance_peg, balance_pegged) / 5)  # this dumps stablecoin

    else:
        assert self.regulator.withdraw_allowed(), "Regulator ban"
        self._withdraw(unsafe_sub(balance_pegged, balance_peg) / 5)  # this pumps stablecoin

    # Send generated profit
    new_profit: uint256 = self._calc_profit()
    assert new_profit >= initial_profit, "peg unprofitable"
    lp_amount: uint256 = new_profit - initial_profit
    caller_profit: uint256 = lp_amount * self.caller_share / SHARE_PRECISION
    if caller_profit > 0:
        POOL.transfer(_beneficiary, caller_profit)

    return caller_profit


@external
@nonpayable
def set_new_caller_share(_new_caller_share: uint256):
    """
    @notice Set new update caller's part
    @param _new_caller_share Part with SHARE_PRECISION
    """
    assert msg.sender == self.admin  # dev: only admin
    assert _new_caller_share <= SHARE_PRECISION  # dev: bad part value

    self.caller_share = _new_caller_share

    log SetNewCallerShare(_new_caller_share)


@external
@nonpayable
def set_new_regulator(_new_regulator: Regulator):
    """
    @notice Set new peg keeper regulator
    """
    assert msg.sender == self.admin  # dev: only admin

    self.regulator = _new_regulator
    log SetNewRegulator(_new_regulator.address)


@external
@nonpayable
def withdraw_profit() -> uint256:
    """
    @notice Withdraw profit generated by Peg Keeper
    @return Amount of LP Token received
    """
    lp_amount: uint256 = self._calc_profit()
    POOL.transfer(self.receiver, lp_amount)

    log Profit(lp_amount)

    return lp_amount


@external
@nonpayable
def commit_new_admin(_new_admin: address):
    """
    @notice Commit new admin of the Peg Keeper
    @param _new_admin Address of the new admin
    """
    assert msg.sender == self.admin  # dev: only admin
    assert self.new_admin_deadline == 0 # dev: active action

    deadline: uint256 = block.timestamp + ADMIN_ACTIONS_DELAY
    self.new_admin_deadline = deadline
    self.future_admin = _new_admin

    log CommitNewAdmin(_new_admin)


@external
@nonpayable
def apply_new_admin():
    """
    @notice Apply new admin of the Peg Keeper
    @dev Should be executed from new admin
    """
    new_admin: address = self.future_admin
    assert msg.sender == new_admin  # dev: only new admin
    assert block.timestamp >= self.new_admin_deadline  # dev: insufficient time
    assert self.new_admin_deadline != 0  # dev: no active action

    self.admin = new_admin
    self.new_admin_deadline = 0

    log ApplyNewAdmin(new_admin)


@external
@nonpayable
def commit_new_receiver(_new_receiver: address):
    """
    @notice Commit new receiver of profit
    @param _new_receiver Address of the new receiver
    """
    assert msg.sender == self.admin  # dev: only admin
    assert self.new_receiver_deadline == 0 # dev: active action

    deadline: uint256 = block.timestamp + ADMIN_ACTIONS_DELAY
    self.new_receiver_deadline = deadline
    self.future_receiver = _new_receiver

    log CommitNewReceiver(_new_receiver)


@external
@nonpayable
def apply_new_receiver():
    """
    @notice Apply new receiver of profit
    """
    assert block.timestamp >= self.new_receiver_deadline  # dev: insufficient time
    assert self.new_receiver_deadline != 0  # dev: no active action

    new_receiver: address = self.future_receiver
    self.receiver = new_receiver
    self.new_receiver_deadline = 0

    log ApplyNewReceiver(new_receiver)


@external
@nonpayable
def revert_new_options():
    """
    @notice Revert new admin of the Peg Keeper or new receiver
    @dev Should be executed from admin
    """
    assert msg.sender == self.admin  # dev: only admin

    self.new_admin_deadline = 0
    self.new_receiver_deadline = 0

    log ApplyNewAdmin(self.admin)
    log ApplyNewReceiver(self.receiver)
