# @version 0.4.1
"""
@title LlamaLend LMCallback
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
@notice LM callback works like a gauge for collateral in LlamaLend/crvUSD AMMs
"""

interface CRV20:
    def future_epoch_time_write() -> uint256: nonpayable
    def rate() -> uint256: view

interface GaugeController:
    def gauge_relative_weight(addr: address, time: uint256) -> uint256: view
    def checkpoint_gauge(addr: address): nonpayable

interface Minter:
    def minted(user: address, gauge: address) -> uint256: view

interface LendingFactory:
    def admin() -> address: view


MAX_TICKS_UINT: constant(uint256) = 50
MAX_TICKS_INT: constant(int256) = 50
WEEK: constant(uint256) = 604800

AMM: public(immutable(address))
CRV: public(immutable(CRV20))
GAUGE_CONTROLLER: public(immutable(GaugeController))
MINTER: public(immutable(Minter))
LENDING_FACTORY: public(immutable(LendingFactory))

is_killed: public(bool)

total_collateral: public(uint256)

collateral_per_share: public(HashMap[int256, uint256])
shares_per_band: public(HashMap[int256, uint256])

user_shares: public(HashMap[address, HashMap[int256, uint256]])
user_start_band: public(HashMap[address,int256])
user_range_size: public(HashMap[address,int256])

# Tracking of mining period
inflation_rate: public(uint256)
future_epoch_time: public(uint256)


# Running integrals
# ------------------
# Definitions:
#
# r - reward rate
# w - gauge relative weight
# s[i] - shares per band i
# cs[i] - collateral per share in band i
# s[u,i] - shares per user in band
#
# Reward rate per collateral:
# rrpc = (r * w) / sum(s[i] * cs[i])
#
# Rewards per collateral (integral):
# I_rpc = integral(rrpc * dt)
# t_rpc - time of the last I_rpc value

struct IntegralRPC:
    rpc: uint256
    t: uint256

I_rpc: public(IntegralRPC)

# Rewards per share:
# I_rps[i] = integral(cs[i] * rrpc * dt) = sum(cs[i] * delta(I_rpc))

struct IntegralRPS:
    rps: uint256
    rpc: uint256

I_rps: public(HashMap[int256, IntegralRPS])

# Rewards per user:
# I_rpu[u,i] = sum(s[u,i] * delta(I_rps[i]))
# I_rpu[u] = sum_i(I_rpu[u,i])

struct IntegralRPU:
    rpu: uint256
    rps: uint256

I_rpu: public(HashMap[address, HashMap[int256, IntegralRPU]])
integrate_fraction: public(HashMap[address, uint256])


@deploy
def __init__(
        amm: address,
        crv: CRV20,
        gauge_controller: GaugeController,
        minter: Minter,
        factory: LendingFactory,
):
    """
    @notice LMCallback constructor. Should be deployed manually.
    @param amm The address of amm
    @param crv The address of CRV token
    @param gauge_controller The address of the gauge controller
    @param minter the address of CRV minter
    """
    AMM = amm
    CRV = crv
    GAUGE_CONTROLLER = gauge_controller
    MINTER = minter
    LENDING_FACTORY = factory

    self.future_epoch_time = extcall crv.future_epoch_time_write()
    self.inflation_rate = staticcall crv.rate()


@internal
def _checkpoint_collateral_shares(n_start: int256, collateral_per_share: DynArray[uint256, MAX_TICKS_UINT], size: int256):
    """
    @notice Checkpoint for shares in a set of bands
    @dev Updates the CRV emission shares are entitled to receive
    @param n_start Index of the first band to checkpoint
    @param collateral_per_share Collateral per share ratio by bands
    @param size The number of bands to checkpoint starting from `n_start`
    """
    # Read current and new rate; update the new rate if needed
    I_rpc: IntegralRPC = self.I_rpc
    rate: uint256 = self.inflation_rate
    new_rate: uint256 = rate
    prev_future_epoch: uint256 = self.future_epoch_time
    if block.timestamp >= prev_future_epoch:
        self.future_epoch_time = extcall CRV.future_epoch_time_write()
        new_rate = staticcall CRV.rate()
        self.inflation_rate = new_rate

    if self.is_killed:
        rate = 0
        new_rate = 0

    # * Record the collateral per share values
    # * Record integrals of rewards per share
    total_collateral: uint256 = self.total_collateral
    delta_rpc: uint256 = 0

    if total_collateral > 0 and block.timestamp > I_rpc.t:  # XXX should we not loop when total_collateral == 0?
        extcall GAUGE_CONTROLLER.checkpoint_gauge(self)
        prev_week_time: uint256 = I_rpc.t
        week_time: uint256 = min((I_rpc.t + WEEK) // WEEK * WEEK, block.timestamp)

        for week_iter: uint256 in range(500):
            dt: uint256 = week_time - prev_week_time
            w: uint256 = staticcall GAUGE_CONTROLLER.gauge_relative_weight(self, prev_week_time)

            if prev_future_epoch >= prev_week_time and prev_future_epoch < week_time:
                # If we went across one or multiple epochs, apply the rate
                # of the first epoch until it ends, and then the rate of
                # the last epoch.
                # If more than one epoch is crossed - the gauge gets less,
                # but that'd mean it wasn't called for more than 1 year
                delta_rpc += rate * w * (prev_future_epoch - prev_week_time) // total_collateral
                rate = new_rate
                delta_rpc += rate * w * (week_time - prev_future_epoch) // total_collateral
            else:
                delta_rpc += rate * w * dt // total_collateral
            # On precisions of the calculation
            # rate ~= 10e18
            # last_weight > 0.01 * 1e18 = 1e16 (if pool weight is 1%)
            # total_collateral ~= TVL * 1e18 ~= 1e26 ($100M for example)
            # The largest loss is at dt = 1
            # Loss is 1e-9 - acceptable

            if week_time == block.timestamp:
                break
            prev_week_time = week_time
            week_time = min(week_time + WEEK, block.timestamp)

    I_rpc.t = block.timestamp
    I_rpc.rpc += delta_rpc
    self.I_rpc = I_rpc

    # Update total_collateral
    for i: int256 in range(MAX_TICKS_INT):
        if i == size:
            break
        _n: int256 = n_start + i
        old_cps: uint256 = self.collateral_per_share[_n]
        cps: uint256 = old_cps
        if len(collateral_per_share) > 0:
            cps = collateral_per_share[i]
            self.collateral_per_share[_n] = cps
        I_rps: IntegralRPS = self.I_rps[_n]
        I_rps.rps += old_cps * (I_rpc.rpc - I_rps.rpc) // 10**18
        I_rps.rpc = I_rpc.rpc
        self.I_rps[_n] = I_rps
        if cps != old_cps:
            spb: uint256 = self.shares_per_band[_n]
            if spb > 0:
                # total_collateral += spb * (cps - old_cps) // 10**18
                old_total_collateral: uint256 = spb * old_cps // 10 ** 18
                total_collateral = max(total_collateral + spb * cps // 10**18, old_total_collateral) - old_total_collateral

    self.total_collateral = total_collateral


@internal
@view
def _user_amounts(user: address, n_start: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT], size: int256) -> uint256[2]:
    """
    @notice Calculates user collateral amount from user bands and shares
    @param user The address of the user
    @param n_start Index of the first band to checkpoint
    @param user_shares User's shares by bands
    @param size The number of bands to checkpoint starting from `n_start`
    @return [
                collateral_amount calculated from passed args,
                old_collateral_amount,
            ]
    """
    old_collateral_amount: uint256 = 0
    collateral_amount: uint256 = 0
    if len(user_shares) > 0:
        for i: int256 in range(MAX_TICKS_INT):
            if i == size:
                break
            cps: uint256 = self.collateral_per_share[n_start + i]
            old_collateral_amount += self.user_shares[user][n_start + i] * cps // 10**18
            collateral_amount += user_shares[i] * cps // 10**18

        return [collateral_amount, old_collateral_amount]
    else:
        for i: int256 in range(MAX_TICKS_INT):
            if i == size:
                break
            old_collateral_amount += self.user_shares[user][n_start + i] * self.collateral_per_share[n_start + i] // 10**18

        return [old_collateral_amount, old_collateral_amount]


@internal
def _checkpoint_user_shares(user: address, n_start: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT], size: int256):
    """
    @notice Checkpoint for user's shares in a set of bands
    @dev Updates the CRV emissions a user is entitled to receive
    @param user The address of the user
    @param n_start Index of the first band to checkpoint
    @param user_shares User's shares by bands
    @param size The number of bands to checkpoint starting from `n_start`
    """
    _amounts: uint256[2] = self._user_amounts(user, n_start, user_shares, size)  # [collateral_amount, old_collateral_amount]
    self.total_collateral = max(self.total_collateral + _amounts[0], _amounts[1]) - _amounts[1]

    rpu: uint256 = self.integrate_fraction[user]
    for i: int256 in range(MAX_TICKS_INT):
        if i == size:
            break
        _n: int256 = n_start + i
        old_user_shares: uint256 = self.user_shares[user][_n]

        if len(user_shares) > 0:
            self.shares_per_band[_n] = self.shares_per_band[_n] + user_shares[i] - self.user_shares[user][_n]
            self.user_shares[user][_n] = user_shares[i]

        I_rpu: IntegralRPU = self.I_rpu[user][_n]
        I_rps: uint256 = self.I_rps[_n].rps
        d_rpu: uint256 = old_user_shares * (I_rps - I_rpu.rps) // 10**18
        I_rpu.rpu += d_rpu
        I_rpu.rps = I_rps
        self.I_rpu[user][_n] = I_rpu
        rpu += d_rpu

    self.integrate_fraction[user] = rpu


@external
@view
def user_collateral(user: address) -> uint256:
    """
    @param user The address of the user
    @return User's collateral amount in LlamaLend/crvUSD AMM
    """
    return self._user_amounts(user, self.user_start_band[user], [], self.user_range_size[user])[0]


@external
def callback_collateral_shares(n_start: int256, collateral_per_share: DynArray[uint256, MAX_TICKS_UINT], size: uint256):
    """
    @notice Checkpoint for shares in a set of bands
    @dev Updates the CRV emission shares are entitled to receive.
         Can be called only be the corresponding AMM.
         It is important that this callback is called every time before callback_user_shares.
    @param n_start Index of the first band to checkpoint
    @param collateral_per_share Collateral per share ratio by bands
    @param size The number of bands to checkpoint starting from `n_start`
    """
    # It is important that this callback is called every time before callback_user_shares
    assert msg.sender == AMM
    self._checkpoint_collateral_shares(n_start, collateral_per_share, convert(size, int256))


@external
def callback_user_shares(user: address, n_start: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT]):
    """
    @notice Checkpoint for user's shares in a set of bands.
    @dev Updates the CRV emissions a user is entitled to receive.
         Can be called only be the corresponding AMM.
    @param user The address of the user
    @param n_start Index of the first band to checkpoint
    @param user_shares User's shares by bands
    """
    assert msg.sender == AMM
    self.user_start_band[user] = n_start
    size: int256 = convert(len(user_shares), int256)
    self.user_range_size[user] = size
    self._checkpoint_user_shares(user, n_start, user_shares, size)


@external
def user_checkpoint(addr: address) -> bool:
    """
    @notice Record a checkpoint for `addr`
    @dev Can be called only by user or CRV minter
    @param addr User address
    @return bool success
    """
    n_start: int256 = self.user_start_band[addr]
    size: int256 = self.user_range_size[addr]
    self._checkpoint_collateral_shares(n_start, [], size)
    self._checkpoint_user_shares(addr, n_start, [], size)

    return True


@external
def claimable_tokens(addr: address) -> uint256:
    """
    @notice Get the number of claimable tokens per user
    @dev This function should be manually changed to "view" in the ABI
    @param addr User address
    @return uint256 number of claimable tokens per user
    """
    n_start: int256 = self.user_start_band[addr]
    size: int256 = self.user_range_size[addr]
    self._checkpoint_collateral_shares(n_start, [], size)
    self._checkpoint_user_shares(addr, n_start, [], size)

    return self.integrate_fraction[addr] - staticcall MINTER.minted(addr, self)


@external
def set_killed(_is_killed: bool):
    """
    @notice Set the killed status for this contract
    @dev When killed, the gauge always yields a rate of 0 and so cannot mint CRV
    @param _is_killed Killed status to set
    """
    assert msg.sender == staticcall LENDING_FACTORY.admin()  # dev: only owner

    self.is_killed = _is_killed
