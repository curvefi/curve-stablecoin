# @version 0.3.10
"""
@title crvUSD FlashLender
@notice ERC3156 contract for crvUSD flash loans
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
"""

from vyper.interfaces import ERC20

interface Factory:
    def stablecoin() -> address: view

interface ERC3156FlashBorrower:
    def onFlashLoan(initiator: address, token: address, amount: uint256, fee: uint256, data: Bytes[10**5]) -> bytes32: nonpayable


CALLBACK_SUCCESS: public(constant(bytes32)) = keccak256("ERC3156FlashBorrower.onFlashLoan")
CRVUSD: immutable(address)
fee: public(constant(uint256)) = 0  # 1 == 0.01 %


@external
def __init__(factory: Factory):
    """
    @notice FlashLender constructor. Gets crvUSD address from factory and gives infinite crvUSD approval to factory.
    """
    CRVUSD = factory.stablecoin()
    ERC20(CRVUSD).approve(factory.address, max_value(uint256))


@external
@view
def supportedTokens(token: address) -> bool:
    return token == CRVUSD


@external
@nonreentrant('lock')
def flashLoan(receiver: ERC3156FlashBorrower, token: address, amount: uint256, data: Bytes[10**5]) -> bool:
    """
    @notice Loan `amount` tokens to `receiver`, and takes it back plus a `flashFee` after the callback
    @param receiver The contract receiving the tokens, needs to implement the
    `onFlashLoan(initiator: address, token: address, amount: uint256, fee: uint256, data: Bytes[10**5])` interface.
    @param token The loan currency.
    @param amount The amount of tokens lent.
    @param data A data parameter to be passed on to the `receiver` for any custom use.
    """
    assert token == CRVUSD, "FlashLender: Unsupported currency"
    assert ERC20(token).transfer(receiver.address, amount, default_return_value=True), "FlashLender: Transfer failed"
    assert receiver.onFlashLoan(msg.sender, token, amount, 0, data) == CALLBACK_SUCCESS, "FlashLender: Callback failed"
    assert ERC20(token).transferFrom(receiver.address, self, amount, default_return_value=True), "FlashLender: Repay failed"

    return True


@external
@view
def flashFee(token: address, amount: uint256) -> uint256:
    """
    @notice The fee to be charged for a given loan.
    @param token The loan currency.
    @param amount The amount of tokens lent.
    @return The amount of `token` to be charged for the loan, on top of the returned principal.
    """
    assert token == CRVUSD, "FlashLender: Unsupported currency"
    return 0


@external
@view
def maxFlashLoan(token: address) -> uint256:
    """
    @notice The amount of currency available to be lent.
    @param token The loan currency.
    @return The amount of `token` that can be borrowed.
    """
    if token == CRVUSD:
        return ERC20(token).balanceOf(self)
    else:
        return 0
