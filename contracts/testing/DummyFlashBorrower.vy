# @version 0.3.10

from vyper.interfaces import ERC20

interface ERC3156FlashLender:
    def flashFee(token: address, amount: uint256) -> uint256: view
    def flashLoan(receiver: address, token: address, amount: uint256, data: Bytes[10**5]) -> bool: nonpayable


CALLBACK_SUCCESS: public(constant(bytes32)) = keccak256("ERC3156FlashBorrower.onFlashLoan")
CALLBACK_ERROR: public(constant(bytes32)) = keccak256("ERC3156FlashBorrower.onFlashLoanERROR")
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
) -> bytes32:
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

    if self.success:
        return CALLBACK_SUCCESS
    else:
        return CALLBACK_ERROR


@external
def flashBorrow(token: address, amount: uint256, success: bool = True, send_back: bool = True):
    """
    @notice Initiate a flash loan.
    """
    self.send_back = send_back
    self.success = success
    ERC3156FlashLender(LENDER).flashLoan(self, token, amount, b"")
