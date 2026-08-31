# pragma version 0.4.3

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment

Makes several calls inside a single transaction, so that tests can drive a
LeverageTransientZap more than once per transaction - the only way to observe whether
the zap's transient stash is really cleared between calls, since the transaction
boundary would wipe it regardless.

Acts as a plain user towards the zap: it is `msg.sender`, so loans are created for the
batcher and refunds come back to it.
"""

MAX_CALLDATA: constant(uint256) = 32 * 400
MAX_CALLS: constant(uint256) = 8

# Per-call success flags of the last `execute`, populated when failures are allowed
last_success: public(DynArray[bool, MAX_CALLS])


@external
def execute(
    _targets: DynArray[address, MAX_CALLS],
    _calldatas: DynArray[Bytes[MAX_CALLDATA], MAX_CALLS],
    _allow_failure: bool = False,
):
    assert len(_targets) == len(_calldatas)
    self.last_success = []

    for i: uint256 in range(len(_calldatas), bound=MAX_CALLS):
        if _allow_failure:
            self.last_success.append(
                raw_call(_targets[i], _calldatas[i], revert_on_failure=False)
            )
        else:
            raw_call(_targets[i], _calldatas[i])
            self.last_success.append(True)
