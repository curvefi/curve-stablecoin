# @version 0.4.1
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

event MaxDeviationSet:
    max_deviation: uint256

MAX_DEVIATION_BPS: constant(uint256) = 5000  # 50%

factory: public(IFactory)
implementation: public(address)
max_deviation: public(uint256)

@deploy
def __init__(_implementation: address, _factory: IFactory, _max_deviation: uint256):
    """
    @notice Initializer for Llamalend oracle proxy
    @param _implementation oracle implementation contract
    @param _factory LlamaLend factory contract
    @param _max_deviation max price deviation when setting new oracle, in BPS (e.g. 500 == 5%)
    """
    assert _max_deviation > 0, "Invalid max deviation"
    assert _max_deviation <= MAX_DEVIATION_BPS, "Invalid max deviation"
    assert _factory.address != empty(address)
    self._validate_price_oracle(_implementation)
    self.implementation = _implementation
    self.factory = _factory
    self.max_deviation = _max_deviation

@internal
def _validate_price_oracle(_oracle: address) -> uint256:
    """
    @notice Validates the new implementation has methods implemented correctly
    """
    assert _oracle != empty(address), "Invalid address"

    block_price: uint256 = staticcall IPriceOracle(_oracle).price()
    assert block_price > 0, "price() call failed"
    assert extcall IPriceOracle(_oracle).price_w() > 0, "price_w() call failed"

    return block_price

@internal
def _check_price_deviation(_old_oracle: address, new_price: uint256):
    """
    @notice Ensures price returned by new implementation is within acceptable bounds
    """
    old_price: uint256 = staticcall IPriceOracle(_old_oracle).price()

    if old_price > 0:
        delta: uint256 = new_price - old_price if old_price < new_price else old_price - new_price
        max_delta: uint256 = old_price * self.max_deviation // 10_000
        assert delta <= max_delta, "Price deviation too high"

@external
def set_price_oracle(_new_implementation: address):
    """
    @notice Sets a new oracle implementation contract
    @param _new_implementation new oracle implementation contract
    """
    assert msg.sender == staticcall self.factory.admin(), "Not authorized"

    block_price: uint256 = self._validate_price_oracle(_new_implementation)

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
        self._check_price_deviation(self.implementation, block_price)

    self.implementation = _new_implementation
    log PriceOracleSet(_new_implementation)

@external
def set_max_deviation(_max_deviation: uint256):
    """
    @notice Allows factory admin to update max price deviation in BPS (e.g. 500 = 5%)
    @param _max_deviation New maximum deviation, must be > 0 and <= MAX_DEVIATION_BPS
    """
    assert msg.sender == staticcall self.factory.admin(), "Not authorized"
    assert _max_deviation > 0, "Invalid deviation"
    assert _max_deviation <= MAX_DEVIATION_BPS, "Deviation too high"

    self.max_deviation = _max_deviation
    log MaxDeviationSet(_max_deviation)

@external
@view
def price() -> uint256:
    """
    @notice Passes price() from implementation contract
    """
    return staticcall IPriceOracle(self.implementation).price()

@external
def price_w() -> uint256:
    """
    @notice Calls price_w() on implementation contract
    """
    return extcall IPriceOracle(self.implementation).price_w()
