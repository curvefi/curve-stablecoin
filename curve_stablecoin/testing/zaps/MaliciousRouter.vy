# pragma version 0.4.3

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment

A DummyRouter-compatible exchange that can be told to misbehave while it sits on the
stack inside a LeverageTransientZap callback - i.e. at the exact moment the zap has
swap parameters stashed in transient storage, holds user funds, and has standing
approvals on the controller.

  * `set_attack` makes it call an arbitrary target with arbitrary calldata in the
    middle of the swap: re-entering a zap entry point, calling a zap callback
    directly, or calling the controller itself.
  * `set_catch_attack(True)` swallows the attack's revert so a test can assert that
    the attack was rejected while the honest operation still completed. Left False,
    the attack's revert bubbles up and the test can assert the exact revert reason.
  * `set_skip_swap` makes `exchange` a no-op, so the zap sees no swap output at all.
  * `set_should_revert` makes the exchange itself revert.
"""

from curve_std.interfaces import IERC20

MAX_ATTACK_CALLDATA: constant(uint256) = 32 * 200

# What to call in the middle of `exchange`, and with what
attack_target: public(address)
attack_calldata: public(Bytes[MAX_ATTACK_CALLDATA])
catch_attack: public(bool)

# Outcome of the last attack attempt
attack_attempted: public(bool)
attack_succeeded: public(bool)

skip_swap: public(bool)
should_revert: public(bool)


@external
def set_attack(_target: address, _calldata: Bytes[MAX_ATTACK_CALLDATA]):
    self.attack_target = _target
    self.attack_calldata = _calldata
    self.attack_attempted = False
    self.attack_succeeded = False


@external
def set_catch_attack(_catch: bool):
    self.catch_attack = _catch


@external
def set_skip_swap(_skip: bool):
    self.skip_swap = _skip


@external
def set_should_revert(_revert: bool):
    self.should_revert = _revert


@external
def approve(_token: IERC20, _spender: address):
    """Let a zap/controller pull tokens from this router when it poses as a user"""
    assert extcall _token.approve(_spender, max_value(uint256), default_return_value=True)


@external
def exchange(in_coin: address, out_coin: address, in_amount: uint256, out_amount: uint256):
    assert not self.should_revert, "router failure"

    if self.attack_target != empty(address):
        self.attack_attempted = True
        if self.catch_attack:
            self.attack_succeeded = raw_call(
                self.attack_target, self.attack_calldata, revert_on_failure=False
            )
        else:
            raw_call(self.attack_target, self.attack_calldata)
            self.attack_succeeded = True

    if not self.skip_swap:
        assert extcall IERC20(in_coin).transferFrom(msg.sender, self, in_amount, default_return_value=True)
        assert extcall IERC20(out_coin).transfer(msg.sender, out_amount, default_return_value=True)
