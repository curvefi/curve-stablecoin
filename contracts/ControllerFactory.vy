# @version 0.3.7

interface ERC20:
    def mint(_to: address, _value: uint256) -> bool: nonpayable
    def burnFrom(_to: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_user: address) -> uint256: view
    def decimals() -> uint256: view

interface PriceOracle:
    def price() -> uint256: view

interface AMM:
    def set_admin(_admin: address): nonpayable

interface Controller:
    def total_debt() -> uint256: view
    def minted() -> uint256: view
    def redeemed() -> uint256: view
    def collect_fees() -> uint256: nonpayable

interface MonetaryPolicy:
    def rate_write() -> uint256: nonpayable


event AddMarket:
    collateral: indexed(address)
    controller: address
    amm: address
    monetary_policy: address
    ix: uint256

event SetDebtCeiling:
    addr: indexed(address)
    debt_ceiling: uint256

event MintForMarket:
    addr: indexed(address)
    amount: uint256

event RemoveFromMarket:
    addr: indexed(address)
    amount: uint256

event SetImplementations:
    amm: address
    controller: address

event SetAdmin:
    admin: address

event SetFeeReceiver:
    fee_receiver: address


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

WETH: public(immutable(address))


@external
def __init__(stablecoin: ERC20,
             admin: address,
             fee_receiver: address,
             weth: address):
    """
    @notice Factory which creates both controllers and AMMs from blueprints
    @param stablecoin Stablecoin address
    @param admin Admin of the factory (ideally DAO)
    @param fee_receiver Receiver of interest and admin fees
    @param weth Address of WETH contract address
    """
    STABLECOIN = stablecoin
    self.admin = admin
    self.fee_receiver = fee_receiver
    WETH = weth


@internal
@pure
def ln_int(_x: uint256) -> int256:
    """
    @notice Logarithm ln() function based on log2. Not very gas-efficient but brief
    """
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
    """
    @notice Set debt ceiling for a market
    @param addr Controller address
    @param debt_ceiling Value for stablecoin debt ceiling
    @param update Whether to actually update the debt ceiling (False is used for burning the residuals)
    """
    old_debt_residual: uint256 = self.debt_ceiling_residual[addr]

    if debt_ceiling > old_debt_residual:
        to_mint: uint256 = debt_ceiling - old_debt_residual
        STABLECOIN.mint(addr, to_mint)
        self.debt_ceiling_residual[addr] = debt_ceiling
        log MintForMarket(addr, to_mint)

    if debt_ceiling < old_debt_residual:
        diff: uint256 = min(old_debt_residual - debt_ceiling, STABLECOIN.balanceOf(addr))
        STABLECOIN.burnFrom(addr, diff)
        self.debt_ceiling_residual[addr] = old_debt_residual - diff
        log RemoveFromMarket(addr, diff)

    if update:
        self.debt_ceiling[addr] = debt_ceiling
        log SetDebtCeiling(addr, debt_ceiling)


@external
@nonreentrant('lock')
def add_market(token: address, A: uint256, fee: uint256, admin_fee: uint256,
               _price_oracle_contract: address,
               monetary_policy: address, loan_discount: uint256, liquidation_discount: uint256,
               debt_ceiling: uint256) -> address[2]:
    """
    @notice Add a new market, creating an AMM and a Controller from a blueprint
    @param token Collateral token address
    @param A Amplification coefficient; one band size is 1/A
    @param fee AMM fee in the market's AMM
    @param admin_fee AMM admin fee
    @param _price_oracle_contract Address of price oracle contract for this market
    @param monetary_policy Monetary policy for this market
    @param loan_discount Loan discount: allowed to borrow only up to x_down * (1 - loan_discount)
    @param liquidation_discount Discount which defines a bad liquidation threshold
    @param debt_ceiling Debt ceiling for this market
    @return (Controller, AMM)
    """
    assert msg.sender == self.admin, "Only admin"
    assert A >= MIN_A and A <= MAX_A, "Wrong A"
    assert fee < MAX_FEE, "Fee too high"
    assert admin_fee < MAX_ADMIN_FEE, "Admin fee too high"
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT, "Liquidation discount too low"
    assert loan_discount <= MAX_LOAN_DISCOUNT, "Loan discount too high"
    assert loan_discount > liquidation_discount, "need loan_discount>liquidation_discount"
    MonetaryPolicy(monetary_policy).rate_write()  # Test that MonetaryPolicy has correct ABI

    p: uint256 = PriceOracle(_price_oracle_contract).price()  # This also validates price oracle ABI
    A_ratio: uint256 = 10**18 * A / (A - 1)

    amm: address = create_from_blueprint(
        self.amm_implementation,
        STABLECOIN.address, 10**(18 - STABLECOIN.decimals()),
        token, 10**(18 - ERC20(token).decimals()),  # <- This validates ERC20 ABI
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
        assert i != 999, "Too many controllers for same collateral"
    self.controllers[N] = controller
    self.amms[N] = amm
    self.n_collaterals = N + 1

    log AddMarket(token, controller, amm, monetary_policy, N)
    return [controller, amm]


@external
@view
def total_debt() -> uint256:
    """
    @notice Sum of all debts across controllers
    """
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
    """
    @notice Get controller address for collateral
    @param collateral Address of collateral token
    @param i Iterate over several controllers for collateral if needed
    """
    return self.controllers[self.collaterals_index[collateral][i] - 2**128]


@external
@view
def get_amm(collateral: address, i: uint256 = 0) -> address:
    """
    @notice Get AMM address for collateral
    @param collateral Address of collateral token
    @param i Iterate over several amms for collateral if needed
    """
    return self.amms[self.collaterals_index[collateral][i] - 2**128]


@external
@nonreentrant('lock')
def set_implementations(controller: address, amm: address):
    """
    @notice Set new implementations (blueprints) for controller and amm. Doesn't change existing ones
    @param controller Address of the controller blueprint
    @param amm Address of the AMM blueprint
    """
    assert msg.sender == self.admin
    assert controller != empty(address)
    assert amm != empty(address)
    self.controller_implementation = controller
    self.amm_implementation = amm
    log SetImplementations(amm, controller)


@external
@nonreentrant('lock')
def set_admin(admin: address):
    """
    @notice Set admin of the factory (should end up with DAO)
    @param admin Address of the admin
    """
    assert msg.sender == self.admin
    self.admin = admin
    log SetAdmin(admin)


@external
@nonreentrant('lock')
def set_fee_receiver(fee_receiver: address):
    """
    @notice Set fee receiver who earns interest (DAO)
    @param fee_receiver Address of the receiver
    """
    assert msg.sender == self.admin
    assert fee_receiver != empty(address)
    self.fee_receiver = fee_receiver
    log SetFeeReceiver(fee_receiver)


@external
@nonreentrant('lock')
def set_debt_ceiling(_to: address, debt_ceiling: uint256):
    """
    @notice Set debt ceiling of the address - mint the token amount given for it
    @param _to Address to allow borrowing for
    @param debt_ceiling Maximum allowed to be allowed to mint for it
    """
    assert msg.sender == self.admin
    self._set_debt_ceiling(_to, debt_ceiling, True)


@external
@nonreentrant('lock')
def rug_debt_ceiling(_to: address):
    """
    @notice Remove stablecoins above the debt ceiling from the address and burn them
    @param _to Address to remove stablecoins from
    """
    self._set_debt_ceiling(_to, self.debt_ceiling[_to], False)


@external
@nonreentrant('lock')
def collect_fees_above_ceiling(_to: address):
    """
    @notice If the receiver is the controller - increase the debt ceiling if it's not enough to claim admin fees
            and claim them
    @param _to Address of the controller
    """
    assert msg.sender == self.admin
    old_debt_residual: uint256 = self.debt_ceiling_residual[_to]
    assert self.debt_ceiling[_to] > 0 or old_debt_residual > 0

    admin_fees: uint256 = Controller(_to).total_debt() + Controller(_to).redeemed() - Controller(_to).minted()
    b: uint256 = STABLECOIN.balanceOf(_to)
    if admin_fees > b:
        to_mint: uint256 = admin_fees - b
        STABLECOIN.mint(_to, to_mint)
        self.debt_ceiling_residual[_to] = old_debt_residual + to_mint
    Controller(_to).collect_fees()
