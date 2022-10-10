# @version 0.3.7

interface ERC20:
    def mint(_to: address, _value: uint256) -> bool: nonpayable
    def burnFrom(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_user: address) -> uint256: view
    def decimals() -> uint256: view

interface PriceOracle:
    def price() -> uint256: view

interface AMM:
    def set_admin(_admin: address): nonpayable

interface Controller:
    def total_debt() -> uint256: view


event AddMarket:
    collateral: address
    controller: address
    amm: address
    monetary_policy: address
    ix: uint256

event SetDebtCeiling:
    addr: address
    debt_ceiling: uint256


MAX_CONTROLLERS: constant(uint256) = 50000
STABLECOIN: immutable(ERC20)
controllers: public(address[MAX_CONTROLLERS])
amms: public(address[MAX_CONTROLLERS])
admin: public(address)
fee_receiver: public(address)
controller_implementation: public(address)
amm_implementation: public(address)

n_collaterals: public(uint256)
collaterals: public(address[MAX_CONTROLLERS])
collaterals_index: public(HashMap[address, uint256[1000]])

debt_ceiling: public(HashMap[address, uint256])
debt_ceiling_residual: public(HashMap[address, uint256])

# Limits
MIN_A: constant(uint256) = 2
MAX_A: constant(uint256) = 10000
MAX_FEE: constant(uint256) = 10**17  # 10%
MAX_ADMIN_FEE: constant(uint256) = 10**18  # 100%
MAX_LOAN_DISCOUNT: constant(uint256) = 5 * 10**17
MIN_LIQUIDATION_DISCOUNT: constant(uint256) = 10**16


@external
def __init__(stablecoin: ERC20,
             admin: address,
             fee_receiver: address):
    STABLECOIN = stablecoin
    self.admin = admin
    self.fee_receiver = fee_receiver


@internal
@pure
def ln_int(_x: uint256) -> int256:
    # Calculate log(A / (A - 1))
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    # This can be much more optimal but that's not important here
    x: uint256 = _x
    res: uint256 = 0
    for i in range(8):
        t: uint256 = 2**(7 - i)
        p: uint256 = 2**t
        if x >= p * 10**18:
            x /= p
            res += t * 10**18
    d: uint256 = 10**18
    for i in range(59):  # 18 decimals: math.log2(10**10) == 59.7
        if (x >= 2 * 10**18):
            res += d
            x /= 2
        x = x * x / 10**18
        d /= 2
    # Now res = log2(x)
    # ln(x) = log2(x) / log2(e)
    return convert(res * 10**18 / 1442695040888963328, int256)
## End of low-level math


@external
@view
def stablecoin() -> ERC20:
    return STABLECOIN


@internal
def _set_debt_ceiling(addr: address, debt_ceiling: uint256, update: bool):
    old_debt_residual: uint256 = self.debt_ceiling_residual[addr]

    if debt_ceiling > old_debt_residual:
        STABLECOIN.mint(addr, debt_ceiling - old_debt_residual)
        self.debt_ceiling_residual[addr] = debt_ceiling

    if debt_ceiling < old_debt_residual:
        diff: uint256 = min(old_debt_residual - debt_ceiling, STABLECOIN.balanceOf(addr))
        STABLECOIN.burnFrom(addr, diff)
        self.debt_ceiling_residual[addr] = old_debt_residual - diff

    if update:
        self.debt_ceiling[addr] = debt_ceiling
        log SetDebtCeiling(addr, debt_ceiling)


@external
@nonreentrant('lock')
def add_market(token: address, A: uint256, fee: uint256, admin_fee: uint256,
               _price_oracle_contract: address,
               monetary_policy: address, loan_discount: uint256, liquidation_discount: uint256,
               debt_ceiling: uint256) -> address[2]:
    assert msg.sender == self.admin, "Only admin"
    assert A >= MIN_A and A <= MAX_A, "Wrong A"
    assert fee < MAX_FEE, "Fee too high"
    assert admin_fee < MAX_ADMIN_FEE, "Admin fee too high"
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT, "Liquidation discount too low"
    assert loan_discount <= MAX_LOAN_DISCOUNT, "Loan discount too high"
    assert loan_discount > liquidation_discount, "need loan_discount>liquidation_discount"

    p: uint256 = PriceOracle(_price_oracle_contract).price()
    A_ratio: uint256 = 10**18 * A / (A - 1)

    amm: address = create_from_blueprint(
        self.amm_implementation,
        STABLECOIN.address, 10**(18 - STABLECOIN.decimals()),
        token, 10**(18 - ERC20(token).decimals()),
        A, isqrt(A_ratio * 10**18), self.ln_int(A_ratio),
        p, fee, admin_fee, _price_oracle_contract,
        code_offset=3)
    controller: address = create_from_blueprint(
        self.controller_implementation,
        token, monetary_policy, loan_discount, liquidation_discount, amm,
        code_offset=3)
    AMM(amm).set_admin(controller)
    self._set_debt_ceiling(controller, debt_ceiling, True)

    N: uint256 = self.n_collaterals
    self.collaterals[N] = token
    for i in range(1000):
        if self.collaterals_index[token][i] == 0:
            self.collaterals_index[token][i] = 2**128 + N
            break
    self.controllers[N] = controller
    self.amms[N] = amm
    self.n_collaterals = N + 1

    log AddMarket(token, controller, amm, monetary_policy, N)
    return [controller, amm]


@external
@view
def total_debt() -> uint256:
    total: uint256 = 0
    n_collaterals: uint256 = self.n_collaterals
    for i in range(MAX_CONTROLLERS):
        if i == n_collaterals:
            break
        total += Controller(self.controllers[i]).total_debt()
    return total


@external
@view
def get_controller(collateral: address, i: uint256 = 0) -> address:
    return self.controllers[self.collaterals_index[collateral][i] - 2**128]


@external
@view
def get_amm(collateral: address, i: uint256 = 0) -> address:
    return self.amms[self.collaterals_index[collateral][i] - 2**128]


@external
@nonreentrant('lock')
def set_implementations(controller: address, amm: address):
    assert msg.sender == self.admin
    self.controller_implementation = controller
    self.amm_implementation = amm


@external
@nonreentrant('lock')
def set_admin(admin: address):
    assert msg.sender == self.admin
    self.admin = admin


@external
@nonreentrant('lock')
def set_fee_receiver(fee_receiver: address):
    assert msg.sender == self.admin
    self.fee_receiver = fee_receiver


@external
@nonreentrant('lock')
def set_debt_ceiling(_to: address, debt_ceiling: uint256):
    assert msg.sender == self.admin
    self._set_debt_ceiling(_to, debt_ceiling, True)


@external
@nonreentrant('lock')
def rug_debt_ceiling(_to: address):
    self._set_debt_ceiling(_to, self.debt_ceiling[_to], False)
