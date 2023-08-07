# @version 0.3.9
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


MAX_TICKS_UINT: constant(uint256) = 50

rate: public(uint256)  # This is toal rate per contract
staked_collateral: public(uint256)
last_timestamp: public(uint256)

collateral_per_share: public(HashMap[int256, uint256])
user_shares: public(HashMap[address, HashMap[int256, uint256]])
shares_per_band: public(HashMap[int256, uint256])  # This only counts staked shares
rate_per_token_integral: public(uint256)  # ∫(rate * 1e18 / staked_tokens dt)
rate_per_token_integrals: public(HashMap[int256, uint256])  # ∫(rate * 1e18 / staked_tokens dt) saved for per-band checkpoints
rewards_per_share_integral: public(HashMap[int256, uint256])  # Σ(collateral_per_share[i] * ∫(rate * 1e18 / staked_tokens dt))
rewards_per_share_integrals: public(HashMap[address, HashMap[int256, uint256]])  # per-user Σ(collateral_per_share[i] * ∫(rate * 1e18 / staked_tokens dt))
user_band_rewards: public(HashMap[address, HashMap[int256, uint256]])  #Σ(S_u[i] * Σ(collateral_per_share[i] * ∫(rate * 1e18 / staked_tokens dt)))

AMM: immutable(address)
COLLATERAL_TOKEN: immutable(ERC20)


@external
def __init__(amm: address, rate: uint256):
    AMM = amm
    COLLATERAL_TOKEN = ERC20(LLAMMA(amm).coins(1))
    self.rate = rate


@external
def callback_collateral_shares(n: int256, collateral_per_share: DynArray[uint256, MAX_TICKS_UINT]):
    # It is important that this callback is called every time before callback_user_shares
    assert msg.sender == AMM

    i: int256 = n
    if len(collateral_per_share) > 0:
        staked_collateral: uint256 = self.staked_collateral
        dt: uint256 = block.timestamp - self.last_timestamp
        rate_per_token_integral: uint256 = self.rate_per_token_integral
        if dt > 0 and staked_collateral > 0:
            rate_per_token_integral += self.rate * 10**18 / staked_collateral * dt
            self.rate_per_token_integral = rate_per_token_integral

        for cps in collateral_per_share:
            old_cps: uint256 = self.collateral_per_share[i]
            self.collateral_per_share[i] = cps
            spb: uint256 = self.shares_per_band[i]
            if spb > 0 and cps != old_cps:
                # It could be that we need to make this line not reverting in underflows
                staked_collateral = staked_collateral + spb * cps / 10**18 - spb * old_cps / 10**18
            self.rewards_per_share_integral[i] = old_cps * (rate_per_token_integral - self.rate_per_token_integrals[i]) / 10**18
            self.rate_per_token_integrals[i] = rate_per_token_integral
            i += 1

        self.staked_collateral = staked_collateral
        self.last_timestamp = block.timestamp


@external
def callback_user_shares(user: address, n: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT]):
    assert msg.sender == AMM
    i: int256 = n
    if len(user_shares) > 0:
        staked_collateral: uint256 = self.staked_collateral
        dt: uint256 = block.timestamp - self.last_timestamp
        if dt > 0 and staked_collateral > 0:
            self.rate_per_token_integral += self.rate * 10**18 / staked_collateral * dt

        for s in user_shares:
            old_s: uint256 = self.user_shares[user][i]
            cps: uint256 = self.collateral_per_share[i]
            self.user_shares[user][i] = s
            self.user_band_rewards[user][i] += s * self.rewards_per_share_integrals[user][i] / 10**18
            self.shares_per_band[i] = self.shares_per_band[i] + s - old_s
            if s != old_s:
                # It could be that we need to make this line not reverting in underflows
                staked_collateral = staked_collateral + cps * s / 10**18 - cps * old_s / 10**18
            self.rewards_per_share_integrals[user][i] = self.rewards_per_share_integral[i]
            i += 1
        self.staked_collateral = staked_collateral
