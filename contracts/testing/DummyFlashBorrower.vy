# @version 0.3.10

interface ERC20:
    def balanceOf(_from: address) -> uint256: view
    def approve(_spender: address, _value: uint256) -> bool: nonpayable

interface ERC3156FlashLender:
    def flashFee(token: address, amount: uint256) -> uint256: view
    def flashLoan(receiver: address, token: address, amount: uint256, data: Bytes[10**5]) -> bool: nonpayable


CALLBACK_SUCCESS: public(constant(bytes32)) = keccak256("ERC3156FlashBorrower.onFlashLoan")
CALLBACK_ERROR: public(constant(bytes32)) = keccak256("ERC3156FlashBorrower.onFlashLoanERROR")
LENDER: public(immutable(address))

count: public(uint256)
total_amount: public(uint256)
success: bool


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

    if self.success:
        return CALLBACK_SUCCESS
    else:
        return CALLBACK_ERROR


@external
def flashBorrow(token: address, amount: uint256, success: bool = True, approve: bool = True):
    """
    @notice Initiate a flash loan.
    """
    _fee: uint256 = ERC3156FlashLender(LENDER).flashFee(token, amount)
    if approve:
        ERC20(token).approve(LENDER, amount + _fee)
    self.success = success
    ERC3156FlashLender(LENDER).flashLoan(self, token, amount, b"")
