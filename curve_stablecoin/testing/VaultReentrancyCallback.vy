# pragma version 0.4.3
"""
Callback contract for e2e reentrancy tests on the Vault.

During a controller callback (create_loan / borrow_more / repay / liquidate)
the controller's nonreentrant lock is held.  Vault.deposit/mint/withdraw/redeem
all call controller.save_rate() at the end; save_rate() is *not* @reentrant,
so any of those calls must revert while the lock is held.

Separately, pricePerShare/convertToAssets/convertToShares are pure views
whose results depend only on totalAssets/totalSupply.  Neither changes during
the callback (no state writes have been committed yet), so the values must
equal those sampled just before the operation.

Usage pattern
-------------
1. Deploy with the vault, its borrowed token, and collateral token.
2. Call set_action() to choose what each callback will attempt.
3. Optionally call seed_vault_shares() first (for WITHDRAW/REDEEM tests).
4. For liquidate PPS tests: pre-fund with borrowed tokens and call
   set_borrowed_to_return() so the callback can satisfy the debt assertion.
5. Drive create_loan / borrow_more / repay / liquidate with this contract
   as the callbacker.
"""

from curve_std.interfaces import IERC20
from curve_stablecoin.interfaces import IVault
from curve_stablecoin import constants as c
from curve_std import token as tkn

ACTION_DEPOSIT:  constant(uint256) = 0
ACTION_MINT:     constant(uint256) = 1
ACTION_WITHDRAW: constant(uint256) = 2
ACTION_REDEEM:   constant(uint256) = 3
ACTION_RECORD:   constant(uint256) = 4  # no reentry – just read view values

vault: public(IVault)
borrowed_token: public(IERC20)
collateral_token: public(IERC20)
action: public(uint256)

# Set before a liquidate or repay PPS test: how many borrowed tokens to return
# so that cb.borrowed >= to_repay is satisfied by the controller.
borrowed_to_return: public(uint256)

# Set before a borrow_more/create_loan callback-only PPS test: how much
# collateral the callback provides back to the AMM.
collateral_to_deposit: public(uint256)

pps_during:                  public(uint256)
convert_to_assets_during:    public(uint256)
convert_to_shares_during:    public(uint256)


@deploy
def __init__(_vault: IVault, _borrowed_token: IERC20, _collateral_token: IERC20):
    self.vault = _vault
    self.borrowed_token = _borrowed_token
    self.collateral_token = _collateral_token
    extcall _borrowed_token.approve(_vault.address, max_value(uint256))


@external
def set_action(_action: uint256):
    self.action = _action


@external
def set_borrowed_to_return(_amount: uint256):
    self.borrowed_to_return = _amount


@external
def set_collateral_to_deposit(_amount: uint256):
    self.collateral_to_deposit = _amount


@external
def seed_vault_shares(_amount: uint256):
    """
    Deposit _amount of borrowed tokens (already held by this contract) into
    the vault so that this contract owns vault shares for withdraw/redeem tests.
    """
    extcall self.vault.deposit(_amount)


@internal
def _try_vault_op(a: uint256):
    """
    Attempt a vault operation via raw_call so the revert can be inspected.
    An empty-bytes revert means the nonreentrant guard fired; re-raise as the
    distinguishable "reentrant" error.  Any other revert is propagated as-is.
    """
    success: bool = False
    response: Bytes[256] = b""
    vault: address = self.vault.address

    if a == ACTION_DEPOSIT:
        assert staticcall self.borrowed_token.balanceOf(self) >= c.WAD
        success, response = raw_call(
            vault,
            abi_encode(c.WAD, method_id("deposit(uint256)")),
            max_outsize=32,
            revert_on_failure=False,
        )
    elif a == ACTION_MINT:
        assert staticcall self.borrowed_token.balanceOf(self) >= staticcall self.vault.previewMint(c.WAD)
        success, response = raw_call(
            vault,
            abi_encode(c.WAD, method_id("mint(uint256)")),
            max_outsize=32,
            revert_on_failure=False,
        )
    elif a == ACTION_WITHDRAW:
        assert staticcall self.vault.balanceOf(self) >= staticcall self.vault.previewWithdraw(c.WAD)
        success, response = raw_call(
            vault,
            abi_encode(c.WAD, method_id("withdraw(uint256)")),
            max_outsize=32,
            revert_on_failure=False,
        )
    elif a == ACTION_REDEEM:
        assert staticcall self.vault.balanceOf(self) >= c.WAD
        success, response = raw_call(
            vault,
            abi_encode(c.WAD, method_id("redeem(uint256)")),
            max_outsize=32,
            revert_on_failure=False,
        )
    else:
        return

    if not success:
        if len(response) == 0:
            raise "reentrant"
        raw_revert(response)


@internal
def _record():
    v: IVault = self.vault
    self.pps_during              = staticcall v.pricePerShare()
    self.convert_to_assets_during = staticcall v.convertToAssets(10**18)
    self.convert_to_shares_during = staticcall v.convertToShares(10**18)


# ---------------------------------------------------------------------------
# Callback implementations
# ---------------------------------------------------------------------------

@external
def callback_deposit(
    user: address,
    borrowed: uint256,
    collateral: uint256,
    debt: uint256,
    calldata: Bytes[c.CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """Used by create_loan and borrow_more.
    Approves controller to pull collateral_to_deposit from this contract."""
    extcall self.collateral_token.approve(msg.sender, max_value(uint256))
    a: uint256 = self.action
    if a == ACTION_RECORD:
        self._record()
    else:
        self._try_vault_op(a)

    collateral_to_deposit: uint256 = self.collateral_to_deposit
    self.collateral_to_deposit = 0

    return [0, collateral_to_deposit]


@external
def callback_repay(
    user: address,
    borrowed: uint256,
    collateral: uint256,
    debt: uint256,
    calldata: Bytes[c.CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    Used by repay.  The controller has already withdrawn the position from the
    AMM and sent `collateral` tokens here.  Approving msg.sender lets the
    controller pull collateral back to return to the borrower.
    """
    tkn.max_approve(self.borrowed_token, msg.sender)
    tkn.max_approve(self.collateral_token, msg.sender)
    a: uint256 = self.action
    if a == ACTION_RECORD:
        self._record()
    else:
        self._try_vault_op(a)

    # borrowed_to_return: cb-provided borrowed tokens pulled by controller.
    # collateral: for full repay → goes to borrower; for partial repay →
    # goes back to AMM.  Returning the full amount keeps all collateral
    # in the expected destination with no cb fee.
    borrowed_to_return: uint256 = self.borrowed_to_return
    self.borrowed_to_return = 0

    return [borrowed_to_return, collateral]


@external
def callback_liquidate(
    user: address,
    borrowed: uint256,
    collateral: uint256,
    debt: uint256,
    calldata: Bytes[c.CALLDATA_MAX_SIZE],
) -> uint256[2]:
    """
    Used by liquidate.  The controller has sent `collateral` tokens here and
    expects at least `to_repay` borrowed tokens back.  Approving msg.sender
    lets the controller pull them.
    """
    tkn.max_approve(self.borrowed_token, msg.sender)
    tkn.max_approve(self.collateral_token, msg.sender)
    a: uint256 = self.action
    if a == ACTION_RECORD:
        self._record()
    else:
        self._try_vault_op(a)

    # Return pre-funded borrowed tokens so cb.borrowed >= to_repay holds.
    borrowed_to_return: uint256 = self.borrowed_to_return
    self.borrowed_to_return = 0

    return [borrowed_to_return, 0]
