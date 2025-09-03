# pragma version 0.4.3

from ethereum.ercs import IERC20

interface ERC3156FlashLender:
    def flashFee(token: address, amount: uint256) -> uint256: view
    def flashLoan(receiver: address, token: address, amount: uint256, data: Bytes[10**5]) -> bool: nonpayable


LENDER: public(immutable(address))

count: public(uint256)
total_amount: public(uint256)
success: bool
send_back: bool


@deploy
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
) -> bytes32:
    """
    @notice ERC-3156 Flash loan callback.
    """
    assert msg.sender == LENDER, "FlashBorrower: Untrusted lender"
    assert initiator == self, "FlashBorrower: Untrusted loan initiator"
    assert data == b"", "Non-empty data"
    assert staticcall IERC20(token).balanceOf(self) == amount
    assert fee == 0

    self.count += 1
    self.total_amount += amount

    if self.send_back:
        extcall IERC20(token).transfer(LENDER, amount + fee)

    return keccak256("ERC3156FlashBorrower.onFlashLoan")

@external
def flashBorrow(token: address, amount: uint256, send_back: bool = True):
    """
    @notice Initiate a flash loan.
    """
    self.send_back = send_back
    extcall ERC3156FlashLender(LENDER).flashLoan(self, token, amount, b"")
