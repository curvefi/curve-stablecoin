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

boosted_collateral: public(uint256)
collateral_per_share: public(HashMap[int256, uint256])
shares_per_band: public(HashMap[int256, uint256])  # This only counts staked shares

boosted_shares: public(HashMap[address, HashMap[int256, uint256]])


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
    # It is important that this callback is called every time before callback_user_shares
    assert msg.sender == AMM

    # At the moment - just record the collateral per share values
    i: int256 = n
    if len(collateral_per_share) > 0:
        boosted_collateral: uint256 = self.boosted_collateral

        for cps in collateral_per_share:
            old_cps: uint256 = self.collateral_per_share[i]
            self.collateral_per_share[i] = cps
            spb: uint256 = self.shares_per_band[i]
            if spb > 0 and cps != old_cps:
                # boosted_collateral += spb * (cps - old_cps) / 10**18
                old_value: uint256 = spb * old_cps / 10**18
                boosted_collateral = max(boosted_collateral + spb * cps / 10**18, old_value) - old_value
            i += 1

        self.boosted_collateral = boosted_collateral

@external
def callback_user_shares(user: address, n: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT]):
    assert msg.sender == AMM

    if len(user_shares) > 0:
        boosted_collateral: uint256 = self.boosted_collateral

        # Calculate the amount of real collateral for the user
        i: int256 = n
        collateral_amount: uint256 = 0
        user_cps: DynArray[uint256, MAX_TICKS_UINT] = []
        for s in user_shares:
            cps: uint256 = self.collateral_per_share[i]
            user_cps.append(cps)
            collateral_amount += s * cps / 10**18
            i += 1

        boost: uint256 = self._update_boost(user, collateral_amount)

        i = n
        j: uint256 = 0
        for unboosted_s in user_shares:
            old_s: uint256 = self.boosted_shares[user][i]
            cps: uint256 = user_cps[j]
            s: uint256 = unboosted_s * boost / 10**18
            self.boosted_shares[user][i] = s
            if s != old_s:
                self.shares_per_band[i] = self.shares_per_band[i] + s - old_s
                # boosted_collateral += cps * (s - old_s) / 10**18
                old_value: uint256 = cps * old_s / 10**18
                boosted_collateral = max(boosted_collateral + cps * s / 10**18, old_value) - old_value
            i += 1
            j += 1

        self.boosted_collateral = boosted_collateral
