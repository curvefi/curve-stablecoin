# @version 0.3.1
from vyper.interfaces import ERC20


COLLATERAL_TOKEN: immutable(address)
BORROWED_TOKEN: immutable(address)
MIN_LIQUIDATION_DISCOUNT: constant(uint256) = 10**16 # Start liquidating when threshold reached

debt: public(HashMap[address, uint256])
amm: public(address)
admin: public(address)
ltv: public(uint256)  # Loan to value at 1e18 base
liquidation_discount: public(uint256)
loan_discount: public(uint256)


@external
def __init__(admin: address, collateral_token: address, borrowed_token: address,
             loan_discount: uint256, liquidation_discount: uint256):
    self.admin = admin
    COLLATERAL_TOKEN = collateral_token
    BORROWED_TOKEN = borrowed_token

    assert loan_discount > liquidation_discount
    assert liquidation_discount >= MIN_LIQUIDATION_DISCOUNT
    self.liquidation_discount = liquidation_discount
    self.loan_discount = loan_discount


@internal
@pure
def log2(_x: uint256) -> uint256:
    # adapted from: https://medium.com/coinmonks/9aef8515136e
    # and vyper log implementation
    res: uint256 = 0
    x: uint256 = _x
    for i in range(8):
        t: uint256 = 2**(7 - i)
        p: uint256 = 2**t
        if x >= p * 10**18:
            x /= p
            res += t * 10**18
    d: uint256 = 10**18
    for i in range(34):  # 10 decimals: math.log(10**10, 2) == 33.2
        if (x >= 2 * 10**18):
            res += d
            x /= 2
        x = x * x / 10**18
        d /= 2
    return res


@external
def set_amm(amm: address):
    assert msg.sender == self.admin
    assert self.amm == ZERO_ADDRESS
    self.amm = amm


@external
def set_admin(admin: address):
    assert msg.sender == self.admin
    self.admin = admin


@external
def borrow(collateral: uint256, debt: uint256, n: uint256, _for: address):
    # Deposit and borrow
    # debt = 0 if _for is nonzero!
    pass


@external
def repay(debt: uint256, _for: address):
    # Or repay all for MAX_UINT256
    # Withdraw if debt become 0
    pass


@external
def liquidate(user: address):
    pass


@external
def self_liquidate():
    pass
