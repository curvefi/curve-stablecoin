# @version 0.3.7
"""
This contract is a draft version of liquidity mining gauge for LLAMMa. It doesn't
account for rate changes for simplicity but it could already be suitable for
rewards streamed with constant rate, as well as for testing the method.

In production version, one needs to make rate variable with checkpoints for the
times rate changes (every week), as well as as gas optimizations are needed.
This contract focuses on readability.

WARNING:
At the moment this contract is unfinished, so not recommended to be used
without understanding.
"""
from vyper.interfaces import ERC20

interface LLAMMA:
    def coins(i: uint256) -> address: view

interface VotingEscrowBoost:
    def adjusted_balance_of(_account: address) -> uint256: view

event UpdateBoost:
    user: indexed(address)
    boost: uint256


MAX_TICKS_UINT: constant(uint256) = 50
TOKENLESS_PRODUCTION: constant(uint256) = 40

AMM: public(immutable(address))
COLLATERAL_TOKEN: public(immutable(ERC20))
VECRV: public(immutable(ERC20))
VEBOOST_PROXY: public(immutable(VotingEscrowBoost))

collateral_for_boost: public(HashMap[address, uint256])
total_collateral_for_boost: public(uint256)
working_supply: public(uint256)
working_balances: public(HashMap[address, uint256])


@external
def __init__(amm: address, vecrv: ERC20, veboost_proxy: VotingEscrowBoost):
    AMM = amm
    COLLATERAL_TOKEN = ERC20(LLAMMA(amm).coins(1))
    VECRV = vecrv
    VEBOOST_PROXY = veboost_proxy


@internal
def _update_boost(user: address, collateral_amount: uint256) -> uint256:
    # To be called after totalSupply is updated
    voting_balance: uint256 = VEBOOST_PROXY.adjusted_balance_of(user)
    voting_total: uint256 = VECRV.totalSupply()

    # collateral_amount and total are used to calculate boosts
    old_amount: uint256 = self.collateral_for_boost[user]
    self.collateral_for_boost[user] = collateral_amount
    L: uint256 = self.total_collateral_for_boost + collateral_amount - old_amount
    self.total_collateral_for_boost = L

    lim: uint256 = collateral_amount * TOKENLESS_PRODUCTION / 100
    if voting_total > 0:
        lim += L * voting_balance / voting_total * (100 - TOKENLESS_PRODUCTION) / 100
    lim = min(collateral_amount, lim)

    old_bal: uint256 = self.working_balances[user]
    self.working_balances[user] = lim
    _working_supply: uint256 = self.working_supply + lim - old_bal
    self.working_supply = _working_supply

    boost: uint256 = lim * 10**18 / _working_supply
    log UpdateBoost(user, boost)

    return boost


@external
def callback_collateral_shares(n: int256, collateral_per_share: DynArray[uint256, MAX_TICKS_UINT]):
    assert msg.sender == AMM

    pass


@external
def callback_user_shares(user: address, n: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT]):
    assert msg.sender == AMM

    pass
