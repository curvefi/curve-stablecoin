# @version 0.3.6

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


event AddMarket:
    collateral: address
    controller: address
    amm: address
    monetary_policy: address

event SetDebtCeiling:
    addr: address
    debt_ceiling: uint256


STABLECOIN: immutable(ERC20)
controllers: public(HashMap[address, address])
amms: public(HashMap[address, address])
admin: public(address)
fee_receiver: public(address)
controller_implementation: public(address)
amm_implementation: public(address)

n_collaterals: public(uint256)
collaterals: public(address[1000000])

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


# Low-level math
@internal
@pure
def sqrt_int(x: uint256) -> uint256:
    # https://github.com/transmissions11/solmate/blob/v7/src/utils/FixedPointMathLib.sol#L288
    _x: uint256 = x * 10**18
    y: uint256 = _x
    z: uint256 = 181
    if y >= 2**(128 + 8):
        y = unsafe_div(y, 2**128)
        z = unsafe_mul(z, 2**64)
    if y >= 2**(64 + 8):
        y = unsafe_div(y, 2**64)
        z = unsafe_mul(z, 2**32)
    if y >= 2**(32 + 8):
        y = unsafe_div(y, 2**32)
        z = unsafe_mul(z, 2**16)
    if y >= 2**(16 + 8):
        y = unsafe_div(y, 2**16)
        z = unsafe_mul(z, 2**8)

    z = unsafe_div(unsafe_mul(z, unsafe_add(y, 65536)), 2**18)

    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    z = unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)
    return unsafe_div(unsafe_add(unsafe_div(_x, z), z), 2)


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
               monetary_policy: address, loan_discount: uint256,
               liquidation_discount: uint256, debt_ceiling: uint256,
               calculated_amm_address: address, calculated_controller_address: address,
               ) -> address[2]:
    assert msg.sender == self.admin, "Only admin"
    assert self.controllers[token] == empty(address) and self.amms[token] == empty(address), "Already exists"
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
        A, self.sqrt_int(A_ratio), self.ln_int(A_ratio),
        p, fee, calculated_controller_address, admin_fee, _price_oracle_contract,
        code_offset=3)

    assert amm == calculated_amm_address  # debug: amm create fail

    controller: address = create_from_blueprint(
        self.controller_implementation,
        token, monetary_policy, loan_discount, liquidation_discount, amm,
        code_offset=3)

    assert controller == calculated_controller_address  # debug: controller create fail

    self._set_debt_ceiling(controller, debt_ceiling, True)

    N: uint256 = self.n_collaterals
    self.collaterals[N] = token
    self.controllers[token] = controller
    self.amms[token] = amm
    self.n_collaterals = N + 1

    log AddMarket(token, controller, amm, monetary_policy)
    return [controller, amm]


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
def rug_debt_ceiling(_to: address, debt_ceiling: uint256):
    self._set_debt_ceiling(_to, self.debt_ceiling[_to], False)
