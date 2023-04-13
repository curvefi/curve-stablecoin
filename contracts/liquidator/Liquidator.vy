# @version 0.3.7

interface ERC20:
    def transfer(_to: address, _value: uint256) -> bool: nonpayable
    def transferFrom(_from: address, _to: address, _value: uint256) -> bool: nonpayable
    def approve(_spender: address, _value: uint256) -> bool: nonpayable
    def balanceOf(_for: address) -> uint256: view

interface CRYPTOPOOL:
    def exchange(i: uint256, j: uint256, dx: uint256, min_dy: uint256) -> uint256: nonpayable

interface LLAMMA_CONTROLLER:
    def liquidate_extended(user: address, min_x: uint256, frac: uint256, use_eth: bool,
                       callbacker: address, callback_sig: bytes32, callback_args: DynArray[uint256,5]): nonpayable

LLAMMA_CONTROLLER_ADDRESS: immutable(address)
CRYPTOPOOL_ADDRESS: immutable(address)
CRVUSD_ADDRESS: immutable(address)
COLLATERAL_ADDRESS: immutable(address)


@external
def __init__(_llamma_controller: address, _cryptopool: address, _crvusd: address, _collateral: address):
    LLAMMA_CONTROLLER_ADDRESS = _llamma_controller
    CRYPTOPOOL_ADDRESS = _cryptopool
    CRVUSD_ADDRESS = _crvusd
    COLLATERAL_ADDRESS = _collateral

    ERC20(_crvusd).approve(_llamma_controller, max_value(uint256), default_return_value=True)
    ERC20(_collateral).approve(_llamma_controller, max_value(uint256), default_return_value=True)
    ERC20(_collateral).approve(_cryptopool, max_value(uint256), default_return_value=True)


@external
def liquidate_callback(user: address, stablecoins: uint256, collateral: uint256, debt: uint256, callback_args: DynArray[uint256, 5]) -> uint256[2]:
    assert msg.sender == LLAMMA_CONTROLLER_ADDRESS

    min_recv: uint256 = (debt - stablecoins) * 1005 / 1000 # 0.5 %
    stablecoins_received: uint256 = CRYPTOPOOL(CRYPTOPOOL_ADDRESS).exchange(1, 0, collateral, min_recv)

    return [stablecoins_received, 0]


@external
@nonreentrant('lock')
def liquidate(user: address, min_x: uint256, frac: uint256 = 10**18, _for: address = msg.sender):
    selector: uint256 = shift(convert(method_id("liquidate_callback(address,uint256,uint256,uint256,uint256[])"), uint256), 224)
    LLAMMA_CONTROLLER(LLAMMA_CONTROLLER_ADDRESS).liquidate_extended(user, min_x, frac, False, self, convert(selector, bytes32), [])

    crvusd_balance: uint256 = ERC20(CRVUSD_ADDRESS).balanceOf(self)
    ERC20(CRVUSD_ADDRESS).transfer(_for, crvusd_balance)
