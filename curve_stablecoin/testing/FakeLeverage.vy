# pragma version 0.4.3
from curve_std.interfaces import IERC20
from curve_stablecoin import constants as c

STABLECOIN: immutable(IERC20)
COLLATERAL: immutable(IERC20)
STABLECOIN_DECIMALS: immutable(uint256)
COLLATERAL_DECIMALS: immutable(uint256)

price: public(uint256)
callback_deposit_hits: public(uint256)
callback_repay_hits: public(uint256)
CALLDATA_MAX_SIZE: constant(uint256) = c.CALLDATA_MAX_SIZE


@deploy
def __init__(stablecoin_token: IERC20, collateral_token: IERC20, controller: address, price: uint256):
    STABLECOIN = stablecoin_token
    COLLATERAL = collateral_token
    STABLECOIN_DECIMALS = convert(staticcall STABLECOIN.decimals(), uint256)
    COLLATERAL_DECIMALS = convert(staticcall COLLATERAL.decimals(), uint256)
    self.price = price

    # It is necessary to approve transfers of these tokens by the controller
    extcall stablecoin_token.approve(controller, max_value(uint256))
    extcall collateral_token.approve(controller, max_value(uint256))

    # This contract will just receive funding in tokens and "swap" them according to the price


@external
def approve_all():
    # Don't do this at home - only for tests!
    extcall STABLECOIN.approve(msg.sender, max_value(uint256))
    extcall COLLATERAL.approve(msg.sender, max_value(uint256))


@external
def callback_deposit(user: address, stablecoins_no_use: uint256, collateral: uint256, debt: uint256, calldata: Bytes[CALLDATA_MAX_SIZE]) -> uint256[2]:
    self.callback_deposit_hits += 1
    min_amount: uint256 = abi_decode(calldata, (uint256))
    assert staticcall STABLECOIN.balanceOf(self) >= debt
    amount_out: uint256 = debt * 10**18 * 10**COLLATERAL_DECIMALS // self.price // 10**STABLECOIN_DECIMALS
    assert amount_out >= min_amount
    return [0, amount_out]


@external
def callback_repay(user: address, stablecoins: uint256, collateral: uint256, debt: uint256, calldata: Bytes[CALLDATA_MAX_SIZE]) -> uint256[2]:
    self.callback_repay_hits += 1
    frac: uint256 = abi_decode(calldata, (uint256))
    s_diff: uint256 = (debt - stablecoins) * frac // 10**18
    # Instead of returning collateral - what_was_spent we could unwrap and send
    # ETH from here to user (if it was ETH), so no need to do it in controller
    return [s_diff, collateral - s_diff * 10**18 * 10**COLLATERAL_DECIMALS // self.price  // 10**STABLECOIN_DECIMALS]


@external
def callback_liquidate(sender: address, stablecoins: uint256, collateral: uint256, debt: uint256, calldata: Bytes[CALLDATA_MAX_SIZE]) -> uint256[2]:
    return [staticcall STABLECOIN.balanceOf(self), collateral]
