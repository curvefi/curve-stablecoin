# @version 0.3.10
"""
@title UniOracle - price oracle for tokens in Uniswap pools, combined with Curve pool for intermediary token
@author Curve.Fi
@license MIT
"""

interface CurvePool:
    def price_oracle(i: uint256) -> uint256: view
    def coins(i: uint256) -> address: view

interface UniOracleReader:
    def quoteSpecificPoolsWithTimePeriod(_baseAmount: uint128, _baseToken: address, _quoteToken: address, _pools: DynArray[address, 1], _period: uint32) -> uint256: view

interface Factory:
    def admin() -> address: view


UNI_ORACLE_READER: constant(address) = 0xB210CE856631EeEB767eFa666EC7C1C57738d438
UNI_ORACLE_PRECISION: constant(uint128) = 10**18
CRVUSD: constant(address) = 0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E
FACTORY: constant(address) = 0xeA6876DDE9e3467564acBeE1Ed5bac88783205E0


period: public(uint32)
UNI_POOL: public(immutable(address))
TOKEN: public(immutable(address))
QUOTE_TOKEN: public(immutable(address))
CURVE_POOL: public(immutable(CurvePool))
CURVE_IX: public(immutable(uint256))


@external
def __init__(uni_pool: address, token: address, quote_token: address, period: uint32,
             curve_pool: CurvePool, curve_ix: uint256):
    UNI_POOL = uni_pool
    TOKEN = token
    QUOTE_TOKEN = quote_token
    self.period = period
    CURVE_POOL = curve_pool
    assert curve_pool.coins(0) == CRVUSD
    CURVE_IX = curve_ix - 1


@internal
@view
def _price() -> uint256:
    uni_price: uint256 = UniOracleReader(UNI_ORACLE_READER).quoteSpecificPoolsWithTimePeriod(
        10**18, TOKEN, QUOTE_TOKEN, [UNI_POOL], self.period)
    curve_price: uint256 = CURVE_POOL.price_oracle(CURVE_IX)
    return uni_price * curve_price / 10**18


@external
@view
def price() -> uint256:
    return self._price()


@external
def price_w() -> uint256:
    return self._price()


@external
def set_period(period: uint32):
    assert msg.sender == Factory(FACTORY).admin()
    self.period = period
