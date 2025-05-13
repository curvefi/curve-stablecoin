# @version 0.3.10
"""
@title OracleProxy
@notice Oracle proxy allowing LlamaLend factory admin to set price oracle contract after deployment
@author Curve.Fi
@license MIT
"""

interface IFactory:
    def admin() -> address: view

interface IPriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

event PriceOracleSet:
    new_implementation: address

MAX_DEVIATION_BPS: constant(uint256) = 5000  # 50%

factory: public(IFactory)
implementation: public(address)
max_deviation: public(uint256)

@external
def __init__(_implementation: address, _factory: IFactory, _max_deviation: uint256):
    """
    @notice Initializer for Llamalend oracle proxy
    @param _implementation oracle implementation contract
    @param _factory LlamaLend factory contract
    @param _max_deviation max price deviation when setting new oracle, in BPS (e.g. 500 == 5%)
    """
    assert _max_deviation > 0, "Invalid max deviation"
    assert _max_deviation <= MAX_DEVIATION_BPS, "Invalid max deviation"
    assert _factory.address != ZERO_ADDRESS
    self._validate_price_oracle(_implementation)
    self.implementation = _implementation
    self.factory = _factory
    self.max_deviation = _max_deviation

@internal
def _validate_price_oracle(_oracle: address):
    """
    @notice Validates the new implementation has methods implemented correctly
    """
    assert _oracle != ZERO_ADDRESS, "Invalid address"
    assert IPriceOracle(_oracle).price() > 0, "price() call failed"
    assert IPriceOracle(_oracle).price_w() > 0, "price_w() call failed"

@internal
def _check_price_deviation(_old_oracle: address, _new_oracle: address):
    """
    @notice Ensures price returned by new implementation is within acceptable bounds
    """
    old_price: uint256 = IPriceOracle(_old_oracle).price()
    new_price: uint256 = IPriceOracle(_new_oracle).price()

    if old_price > 0:
        delta: uint256 = 0
        if old_price >= new_price:
            delta = old_price - new_price
        else:
            delta = new_price - old_price

        max_delta: uint256 = old_price * self.max_deviation / 10_000
        assert delta <= max_delta, "Price deviation too high"

@external
def set_price_oracle(_new_implementation: address):
    """
    @notice Sets a new oracle implementation contract
    @param _new_implementation new oracle implementation contract
    """
    assert msg.sender == self.factory.admin(), "Not authorized"

    self._validate_price_oracle(_new_implementation)

    # If current implementation price() is borked,
    # skip the price deviation check
    success: bool = False
    response: Bytes[32] = b""

    success, response = raw_call(
        self.implementation,
        method_id("price()"),
        max_outsize=32,
        is_static_call=True,
        revert_on_failure=False
    )

    if success:
        self._check_price_deviation(self.implementation, _new_implementation)

    self.implementation = _new_implementation
    log PriceOracleSet(_new_implementation)

@external
def set_max_deviation(_max_deviation: uint256):
    """
    @notice Allows factory admin to update max price deviation in BPS (e.g. 500 = 5%)
    @param _max_deviation New maximum deviation, must be > 0 and <= MAX_DEVIATION_BPS
    """
    assert msg.sender == self.factory.admin(), "Not authorized"
    assert _max_deviation > 0, "Invalid deviation"
    assert _max_deviation <= MAX_DEVIATION_BPS, "Deviation too high"

    self.max_deviation = _max_deviation

@external
@view
def price() -> uint256:
    """
    @notice Passes price() from implementation contract
    """
    return IPriceOracle(self.implementation).price()
    
@external
def price_w() -> uint256:
    """
    @notice Calls price_w() on implementation contract
    """
    return IPriceOracle(self.implementation).price_w()