# @version 0.4.1
"""
@title OracleProxy
@notice Oracle proxy allowing LlamaLend factory admin to set price oracle contract after deployment
@author Curve.Fi
@license MIT
"""


interface IFactory:
    def owner() -> address: view
    def admin() -> address: view

interface IPriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable


event PriceOracleSet:
    oracle: address

event MaxDeviationSet:
    max_deviation: uint256


MAX_DEVIATION_BPS: constant(uint256) = 5000  # 50%

FACTORY: public(immutable(IFactory))
USE_OWNER: immutable(bool)

oracle: public(IPriceOracle)
max_deviation: public(uint256)


@deploy
def __init__(_oracle: IPriceOracle, _factory: IFactory, _max_deviation: uint256):
    """
    @notice Initializer for Llamalend oracle proxy
    @param _oracle Oracle contract
    @param _factory LlamaLend factory contract
    @param _max_deviation Max price deviation when setting new oracle, in BPS (e.g. 500 == 5%)
    """
    assert _max_deviation > 0 and _max_deviation <= MAX_DEVIATION_BPS, "Invalid max deviation"
    assert _factory.address != empty(address)
    self._validate_price_oracle(_oracle)
    self.oracle = _oracle
    FACTORY = _factory
    self.max_deviation = _max_deviation

    success: bool = False
    response: Bytes[32] = b""
    success, response = raw_call(
        _factory.address,
        method_id("owner()"),
        max_outsize=32,
        is_static_call=True,
        revert_on_failure=False
    )
    if len(response) == 0:
        success = False

    USE_OWNER = success

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
def _check_admin():
    """
    @notice Throws if the sender is not the owner/admin.
    """
    if USE_OWNER:
        assert msg.sender == staticcall FACTORY.owner(), "Not authorized"
    else:
        assert msg.sender == staticcall FACTORY.admin(), "Not authorized"


@internal
def _check_price_deviation(old_price: uint256, new_price: uint256):
    """
    @notice Ensures price returned by new oracle is within acceptable bounds
    """
    delta: uint256 = new_price - old_price if old_price < new_price else old_price - new_price
    max_delta: uint256 = old_price * self.max_deviation // 10_000
    assert delta <= max_delta, "Price deviation too high"


@external
def set_price_oracle(_new_oracle: IPriceOracle):
    """
    @notice Sets the new oracle contract
    @param _new_oracle The new oracle contract
    """
    self._check_admin()

    new_price: uint256 = self._validate_price_oracle(_new_oracle)

    # If current oracle price() is borked,
    # skip the price deviation check
    success: bool = False
    response: Bytes[32] = b""

    success, response = raw_call(
        self.oracle.address,
        method_id("price()"),
        max_outsize=32,
        is_static_call=True,
        revert_on_failure=False
    )

    if success and len(response) > 0:
        old_price: uint256 = abi_decode(response, uint256)
        if old_price > 0:
            self._check_price_deviation(old_price, new_price)

    self.oracle = _new_oracle

    log PriceOracleSet(oracle=_new_oracle.address)


@external
def set_max_deviation(_max_deviation: uint256):
    """
    @notice Allows factory admin to update max price deviation in BPS (e.g. 500 = 5%)
    @param _max_deviation New maximum deviation, must be > 0 and <= MAX_DEVIATION_BPS
    """
    self._check_admin()
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
