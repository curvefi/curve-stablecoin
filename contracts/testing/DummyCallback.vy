# pragma version 0.4.3
from curve_std import token as tkn
from curve_std.interfaces import IERC20
from contracts import constants as c

callback_deposit_hits: public(uint256)
callback_repay_hits: public(uint256)
callback_liquidate_hits: public(uint256)


@internal
def _callback(calldata: Bytes[c.CALLDATA_MAX_SIZE]) -> uint256[2]:
    borrowed_token: IERC20 = empty(IERC20)
    collateral_token: IERC20 = empty(IERC20)
    borrowed_amount: uint256 = 0
    collateral_amount: uint256 = 0
    borrowed_token, collateral_token, borrowed_amount, collateral_amount = \
        abi_decode(calldata, (IERC20, IERC20, uint256, uint256,))

    tkn.max_approve(borrowed_token, msg.sender)
    tkn.max_approve(collateral_token, msg.sender)

    assert staticcall borrowed_token.balanceOf(self) >= borrowed_amount, "Not enough borrowed tokens in callback contract"
    assert staticcall collateral_token.balanceOf(self) >= collateral_amount, "Not enough collaterals token in callback contract"

    return [borrowed_amount, collateral_amount]


@external
def callback_deposit(user: address, borrowed: uint256, collateral: uint256,
                     debt: uint256, calldata: Bytes[c.CALLDATA_MAX_SIZE]) -> uint256[2]:
    self.callback_deposit_hits += 1
    return self._callback(calldata)


@external
def callback_repay(user: address, borrowed: uint256, collateral: uint256,
                   debt: uint256, calldata: Bytes[c.CALLDATA_MAX_SIZE]) -> uint256[2]:
    self.callback_repay_hits += 1
    return self._callback(calldata)


@external
def callback_liquidate(sender: address, stablecoins: uint256, collateral: uint256,
                       debt: uint256, calldata: Bytes[c.CALLDATA_MAX_SIZE]) -> uint256[2]:
    self.callback_liquidate_hits += 1
    return self._callback(calldata)
