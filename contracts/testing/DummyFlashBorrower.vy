# @version 0.3.10

from vyper.interfaces import ERC20

interface ERC3156FlashLender:
    def flashFee(token: address, amount: uint256) -> uint256: view
    def flashLoan(receiver: address, token: address, amount: uint256, data: Bytes[10**5]) -> bool: nonpayable


LENDER: public(immutable(address))

count: public(uint256)
total_amount: public(uint256)
success: bool
send_back: bool


@external
def __init__(_lender: address):
    """
    @notice FlashBorrower constructor. Gets FlashLender address.
    """
    LENDER = _lender


@external
def onFlashLoan(
    initiator: address,
    token: address,
    amount: uint256,
    fee: uint256,
    data: Bytes[10 ** 5],
):
    """
    @notice ERC-3156 Flash loan callback.
    """
    assert msg.sender == LENDER, "FlashBorrower: Untrusted lender"
    assert initiator == self, "FlashBorrower: Untrusted loan initiator"
    assert data == b"", "Non-empty data"
    assert ERC20(token).balanceOf(self) == amount
    assert fee == 0

    self.count += 1
    self.total_amount += amount

    if self.send_back:
        ERC20(token).transfer(LENDER, amount + fee)


@external
def flashBorrow(token: address, amount: uint256, send_back: bool = True):
    """
    @notice Initiate a flash loan.
    """
    self.send_back = send_back
    ERC3156FlashLender(LENDER).flashLoan(self, token, amount, b"")
