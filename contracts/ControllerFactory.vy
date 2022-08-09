# @version 0.3.6

interface ERC20:
    def mint(_to: address, _value: uint256) -> bool: nonpayable
    def burnFrom(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_user: address) -> uint256: view

interface Controller:
    def initialize(
        collateral_token: address, monetary_policy: address,
        loan_discount: uint256, liquidation_discount: uint256,
        amm: address
    ): nonpayable

interface PriceOracle:
    def price() -> uint256: view

interface AMM:
    def initialize(
        _A: uint256, _base_price: uint256, _collateral_token: address, fee: uint256, admin_fee: uint256,
        _price_oracle_contract: address, _admin: address
    ): nonpayable


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
    assert self.controllers[token] == empty(address) and self.amms[token] == empty(address), "Already exists"
    assert A >= MIN_A and A <= MAX_A, "Wrong A"
    assert fee < MAX_FEE, "Fee too high"
    assert admin_fee < MAX_ADMIN_FEE, "Admin fee too high"
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT, "Liquidation discount too low"
    assert loan_discount <= MAX_LOAN_DISCOUNT, "Loan discount too high"
    assert loan_discount > liquidation_discount, "need loan_discount>liquidation_discount"

    p: uint256 = PriceOracle(_price_oracle_contract).price()

    amm: address = create_minimal_proxy_to(self.amm_implementation)
    controller: address = create_minimal_proxy_to(self.controller_implementation)
    AMM(amm).initialize(A, p, token, fee, admin_fee, _price_oracle_contract, controller)
    Controller(controller).initialize(token, monetary_policy, loan_discount, liquidation_discount, amm)
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
