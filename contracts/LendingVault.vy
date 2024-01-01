# @version 0.3.10
"""
@title ERC4626+ Vault for lending with crvUSD using LLAMMA algorithm
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""
from vyper.interfaces import ERC20Detailed


interface AMM:
    def set_admin(_admin: address): nonpayable

interface Controller:
    def total_debt() -> uint256: view
    def minted() -> uint256: view
    def redeemed() -> uint256: view

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

interface MonetaryPolicy:
    def rate_write() -> uint256: nonpayable


# ERC20 events

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256


# Limits
MIN_A: constant(uint256) = 2
MAX_A: constant(uint256) = 10000
MIN_FEE: constant(uint256) = 10**6  # 1e-12, still needs to be above 0
MAX_FEE: constant(uint256) = 10**17  # 10%
MAX_ADMIN_FEE: constant(uint256) = 10**18  # 100%
MAX_LOAN_DISCOUNT: constant(uint256) = 5 * 10**17
MIN_LIQUIDATION_DISCOUNT: constant(uint256) = 10**16

STABLECOIN: public(immutable(ERC20Detailed))

borrowed_token: public(ERC20Detailed)
collateral_token: public(ERC20Detailed)

monetary_policy: public(address)
price_oracle_contract: public(address)

amm: public(AMM)
controller: public(Controller)


# ERC20 publics

decimals: public(uint8)
name: public(String[64])
symbol: public(String[32])

NAME_PREFIX: constant(String[16]) = 'Curve Vault for '
SYMBOL_PREFIX: constant(String[2]) = 'cv'

allowance: public(HashMap[address, HashMap[address, uint256]])
balanceOf: public(HashMap[address, uint256])
totalSupply: public(uint256)


@external
def __init__(stablecoin: ERC20Detailed):
    # The contract is made a "normal" template (not blueprint) so that we can get contract address before init
    # This is needed if we want to create a rehypothecation dual-market with two vaults
    # where vaults are collaterals of each other
    self.borrowed_token = ERC20Detailed(0x0000000000000000000000000000000000000001)
    STABLECOIN = stablecoin


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


@external
def initialize(
        amm_impl: address,
        controller_impl: address,
        borrowed_token: ERC20Detailed,
        collateral_token: ERC20Detailed,
        A: uint256,
        fee: uint256,
        admin_fee: uint256,
        price_oracle_contract: address,  # Factory makes from template if needed, deploying with a from_pool()
        monetary_policy: address,  # Standard monetary policy set in factory
        loan_discount: uint256,
        liquidation_discount: uint256
    ) -> address[2]:
    assert self.borrowed_token.address == empty(address)
    assert STABLECOIN == borrowed_token or STABLECOIN == collateral_token

    self.borrowed_token = borrowed_token
    self.collateral_token = collateral_token
    self.monetary_policy = monetary_policy
    self.price_oracle_contract = price_oracle_contract

    assert A >= MIN_A and A <= MAX_A, "Wrong A"
    assert fee <= MAX_FEE, "Fee too high"
    assert fee >= MIN_FEE, "Fee too low"
    assert admin_fee < MAX_ADMIN_FEE, "Admin fee too high"
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT, "Liquidation discount too low"
    assert loan_discount <= MAX_LOAN_DISCOUNT, "Loan discount too high"
    assert loan_discount > liquidation_discount, "need loan_discount>liquidation_discount"
    MonetaryPolicy(monetary_policy).rate_write()  # Test that MonetaryPolicy has correct ABI

    p: uint256 = PriceOracle(price_oracle_contract).price()  # This also validates price oracle ABI
    assert p > 0
    assert PriceOracle(price_oracle_contract).price_w() == p
    A_ratio: uint256 = 10**18 * A / (A - 1)

    amm: address = create_from_blueprint(
        amm_impl,
        borrowed_token.address, 10**(18 - borrowed_token.decimals()),
        collateral_token.address, 10**(18 - collateral_token.decimals()),
        A, isqrt(A_ratio * 10**18), self.ln_int(A_ratio),
        p, fee, admin_fee, price_oracle_contract,
        code_offset=3)
    controller: address = create_from_blueprint(
        controller_impl,
        empty(address), monetary_policy, loan_discount, liquidation_discount, amm,
        code_offset=3)
    AMM(amm).set_admin(controller)

    self.amm = AMM(amm)
    self.controller = Controller(controller)

    # ERC20 set up
    self.decimals = borrowed_token.decimals()
    borrowed_symbol: String[32] = borrowed_token.symbol()
    self.name = concat(NAME_PREFIX, borrowed_symbol)
    self.symbol = concat(SYMBOL_PREFIX, slice(borrowed_symbol, 0, 30))

    # No events because it's the only market we would ever create in this contract

    return [controller, amm]


@external
@view
def asset() -> ERC20Detailed:
    """
    Method returning borrowed asset address for ERC4626 compatibility
    """
    return self.borrowed_token
