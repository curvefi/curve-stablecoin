# @version 0.3.10
"""
Vault for crvUSD lending (either for using it as collateral, or borrowing).

With this type of vault, the collateral is not being lent out.
"""

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def approve(_spender: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_user: address) -> uint256: view
    def decimals() -> uint256: view

COLLATERAL_TOKEN: public(immutable(ERC20))
BORROWED_TOKEN: public(immutable(ERC20))
BORROWED_PRECISION: public(immutable(uint256))
COLLATERAL_PRECISION: public(immutable(uint256))
PRICE_ORACLE: public(immutable(PriceOracle))
ADMIN: public(immutable(address))

min_rate: public(uint256)
max_rate: public(uint256)
# Example rates:
# 0.5% APR = 158548959
# 50% APR = 15854895991


@external
def __init__(collateral_token: ERC20,
             borrowed_token: ERC20,
             price_oracle: PriceOracle,
             min_rate: uint256,
             max_rate: uint256,
             admin: address):
    COLLATERAL_TOKEN = collateral_token
    BORROWED_TOKEN = borrowed_token
    COLLATERAL_PRECISION = 10 ** (18 - collateral_token.decimals())
    BORROWED_PRECISION = 10 ** (18 - borrowed_token.decimals())
    PRICE_ORACLE = price_oracle
    ADMIN = admin
    self.min_rate = min_rate
    self.max_rate = max_rate
