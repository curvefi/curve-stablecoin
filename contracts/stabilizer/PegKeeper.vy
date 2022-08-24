# @version 0.3.6
"""
@title Peg Keeper
@license MIT
@author Curve.Fi
@notice Peg Keeper for pool with equal decimals of coins
"""


interface CurvePool:
    def balances(i_coin: uint256) -> uint256: view
    def coins(i: uint256) -> address: view
    def lp_token() -> address: view
    def add_liquidity(_amounts: uint256[2], _min_mint_amount: uint256) -> uint256: nonpayable
    def remove_liquidity_imbalance(_amounts: uint256[2], _max_burn_amount: uint256) -> uint256: nonpayable
    def get_virtual_price() -> uint256: view
    def balanceOf(arg0: address) -> uint256: view
    def transfer(_to : address, _value : uint256) -> bool: nonpayable

interface ERC20Pegged:
    def approve(_spender: address, _amount: uint256): nonpayable
    def mint(_to: address, _amount: uint256): nonpayable
    def burn(_amount: uint256): nonpayable
    def balanceOf(arg0: address) -> uint256: view


event Provide:
    amount: uint256


event Withdraw:
    amount: uint256


event Profit:
    lp_amount: uint256


# Time between providing/withdrawing coins
ACTION_DELAY: constant(uint256) = 15 * 60
ADMIN_ACTIONS_DELAY: constant(uint256) = 3 * 86400

PRECISION: constant(uint256) = 10 ** 18
# Calculation error for profit
PROFIT_THRESHOLD: constant(uint256) = 10 ** 18

POOL: immutable(address)
I: immutable(uint256)  # index of pegged in pool
PEGGED: immutable(address)

last_change: public(uint256)
debt: public(uint256)

SHARE_PRECISION: constant(uint256) = 10 ** 5
caller_share: public(uint256)

admin: public(address)
future_admin: public(address)

# Receiver of profit
receiver: public(address)
future_receiver: public(address)

admin_actions_deadline: public(uint256)

FACTORY: immutable(address)


@external
def __init__(_pool: address, _index: uint256, _receiver: address, _caller_share: uint256, _factory: address):
    """
    @notice Contract constructor
    @param _pool Contract pool address
    @param _index Index of the pegged
    @param _receiver Receiver of the profit
    @param _caller_share Caller's share of profit
    @param _factory Factory which should be able to take coins away
    """
    POOL = _pool
    I = _index
    pegged: address = CurvePool(_pool).coins(_index)
    PEGGED = pegged
    ERC20Pegged(pegged).approve(_pool, max_value(uint256))
    ERC20Pegged(pegged).approve(_factory, max_value(uint256))

    self.admin = msg.sender
    self.receiver = _receiver

    self.caller_share = _caller_share

    FACTORY = _factory


@pure
@external
def factory() -> address:
    return FACTORY


@pure
@external
def pegged() -> address:
    return PEGGED


@pure
@external
def pool() -> address:
    return POOL


@internal
def _provide(_amount: uint256):
    # We already have all reserves here
    # ERC20Pegged(PEGGED).mint(self, _amount)

    amounts: uint256[2] = empty(uint256[2])
    amounts[I] = _amount
    CurvePool(POOL).add_liquidity(amounts, 0)

    self.last_change = block.timestamp
    self.debt += _amount
    log Provide(_amount)


@internal
def _withdraw(_amount: uint256):
    debt: uint256 = self.debt
    amount: uint256 = _amount
    if amount > debt:
        amount = debt

    amounts: uint256[2] = empty(uint256[2])
    amounts[I] = amount
    CurvePool(POOL).remove_liquidity_imbalance(amounts, max_value(uint256))

    self.last_change = block.timestamp
    self.debt -= amount

    log Withdraw(amount)


@internal
@view
def _calc_profit() -> uint256:
    lp_balance: uint256 = CurvePool(POOL).balanceOf(self)

    virtual_price: uint256 = CurvePool(POOL).get_virtual_price()
    lp_debt: uint256 = self.debt * PRECISION / virtual_price

    if lp_balance <= lp_debt + PROFIT_THRESHOLD:
        return 0
    else:
        return lp_balance - lp_debt - PROFIT_THRESHOLD


@external
@view
def calc_profit() -> uint256:
    """
    @notice Calculate generated profit in LP tokens
    @return Amount of generated profit
    """
    return self._calc_profit()


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

    balance_pegged: uint256 = CurvePool(POOL).balances(I)
    balance_peg: uint256 = CurvePool(POOL).balances(1 - I)

    initial_profit: uint256 = self._calc_profit()

    if balance_peg > balance_pegged:
        self._provide((balance_peg - balance_pegged) / 5)
    else:
        self._withdraw((balance_pegged - balance_peg) / 5)

    # Send generated profit
    new_profit: uint256 = self._calc_profit()
    assert new_profit >= initial_profit  # dev: peg was unprofitable
    lp_amount: uint256 = new_profit - initial_profit
    caller_profit: uint256 = lp_amount * self.caller_share / SHARE_PRECISION
    CurvePool(POOL).transfer(_beneficiary, caller_profit)

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


@external
@nonpayable
def withdraw_profit() -> uint256:
    """
    @notice Withdraw profit generated by Peg Keeper
    @return Amount of LP Token received
    """
    lp_amount: uint256 = self._calc_profit()
    CurvePool(POOL).transfer(self.receiver, lp_amount)

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
    assert self.admin_actions_deadline == 0 # dev: active action

    deadline: uint256 = block.timestamp + ADMIN_ACTIONS_DELAY
    self.admin_actions_deadline = deadline
    self.future_admin = _new_admin


@external
@nonpayable
def apply_new_admin():
    """
    @notice Apply new admin of the Peg Keeper
    @dev Should be executed from new admin
    """
    assert msg.sender == self.future_admin  # dev: only new admin
    assert block.timestamp >= self.admin_actions_deadline  # dev: insufficient time
    assert self.admin_actions_deadline != 0  # dev: no active action

    self.admin = self.future_admin
    self.admin_actions_deadline = 0


@external
@nonpayable
def commit_new_receiver(_new_receiver: address):
    """
    @notice Commit new receiver of profit
    @param _new_receiver Address of the new receiver
    """
    assert msg.sender == self.admin  # dev: only admin
    assert self.admin_actions_deadline == 0 # dev: active action

    deadline: uint256 = block.timestamp + ADMIN_ACTIONS_DELAY
    self.admin_actions_deadline = deadline
    self.future_receiver = _new_receiver


@external
@nonpayable
def apply_new_receiver():
    """
    @notice Apply new receiver of profit
    """
    assert block.timestamp >= self.admin_actions_deadline  # dev: insufficient time
    assert self.admin_actions_deadline != 0  # dev: no active action

    self.receiver = self.future_receiver
    self.admin_actions_deadline = 0


@external
@nonpayable
def revert_new_staff():
    """
    @notice Revert new admin of the Peg Keeper
    @dev Should be executed from admin
    """
    assert msg.sender == self.admin  # dev: only admin

    self.admin_actions_deadline = 0
