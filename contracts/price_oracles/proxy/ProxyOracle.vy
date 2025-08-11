# @version 0.4.3
#pragma optimize gas
#pragma evm-version shanghai

"""
@title ProxyOracle
@author Curve
@license MIT
@notice Proxy oracle allowing LlamaLend factory admin to set price oracle contract after deployment
"""


interface IFactory:
    def owner() -> address: view

interface IPriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


event PriceOracleSet:
    oracle: address

event MaxDeviationSet:
    max_deviation: uint256


MAX_DEVIATION_BPS: constant(uint256) = 5000  # 50%

factory: public(IFactory)
oracle: public(IPriceOracle)
max_deviation: public(uint256)


@deploy
def __init__():
    """
    @notice Template for OracleProxy implementation
    """
    self.oracle = IPriceOracle(0x0000000000000000000000000000000000000001)


@external
def initialize(_oracle: IPriceOracle, _max_deviation: uint256 = 100):
    """
    @notice Initializer for Llamalend oracle proxy
    @param _oracle Oracle contract
    @param _max_deviation Max price deviation when setting new oracle, in BPS (e.g. 500 == 5%)
    """
    assert self.oracle.address == empty(address), "Already initialized"
    assert _max_deviation > 0 and _max_deviation <= MAX_DEVIATION_BPS, "Invalid max deviation"
    self._validate_price_oracle(_oracle)

    self.oracle = _oracle
    self.max_deviation = _max_deviation
    self.factory = IFactory(msg.sender)

    log PriceOracleSet(oracle=_oracle.address)
    log MaxDeviationSet(max_deviation=_max_deviation)


@internal
def _validate_price_oracle(_oracle: IPriceOracle) -> uint256:
    """
    @notice Validates the new oracle has methods implemented correctly
    """
    assert _oracle.address != empty(address), "Invalid address"

    block_price: uint256 = extcall _oracle.price_w()
    assert staticcall _oracle.price() > 0, "price() call failed"
    assert block_price > 0, "price_w() call failed"

    return block_price


@internal
def _check_price_deviation(old_price: uint256, new_price: uint256):
    """
    @notice Ensures price returned by new oracle is within acceptable bounds
    """
    delta: uint256 = new_price - old_price if old_price < new_price else old_price - new_price
    max_delta: uint256 = old_price * self.max_deviation // 10_000
    assert delta <= max_delta, "Price deviation too high"


@external
def set_price_oracle(_new_oracle: IPriceOracle, _skip_price_deviation_check: bool = False):
    """
    @notice Sets the new oracle contract
    @param _new_oracle The new oracle contract
    """
    assert msg.sender == self.factory.address, "Not authorized"

    new_price: uint256 = self._validate_price_oracle(_new_oracle)
    if not _skip_price_deviation_check:
        self._check_price_deviation(staticcall self.oracle.price(), new_price)

    self.oracle = _new_oracle

    log PriceOracleSet(oracle=_new_oracle.address)


@external
def set_max_deviation(_max_deviation: uint256):
    """
    @notice Allows factory admin to update max price deviation in BPS (e.g. 500 = 5%)
    @param _max_deviation New maximum deviation, must be > 0 and <= MAX_DEVIATION_BPS
    """
    assert msg.sender == staticcall self.factory.owner(), "Not authorized"
    assert _max_deviation > 0 and _max_deviation <= MAX_DEVIATION_BPS, "Invalid deviation"

    self.max_deviation = _max_deviation

    log MaxDeviationSet(max_deviation=_max_deviation)


@external
@view
def price() -> uint256:
    """
    @notice Passes price() from oracle contract
    """
    return staticcall self.oracle.price()


@external
def price_w() -> uint256:
    """
    @notice Calls price_w() on oracle contract
    """
    return extcall self.oracle.price_w()
