# @version 0.4.1
"""
@title LlamaLend LMCallback
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
@notice LM callback works like a gauge for collateral in LlamaLend/crvUSD AMMs
"""

from ethereum.ercs import IERC20

interface ILLAMMA:
    def coins(i: uint256) -> address: view
    def get_sum_xy(user: address) -> uint256[2]: view
    def read_user_tick_numbers(user: address) -> int256[2]: view
    def read_user_ticks(user: address, ns: int256[2]) -> DynArray[uint256, MAX_TICKS_UINT]: view
    def admin_fees_y() -> uint256: view
    def user_shares(user: address) -> UserTicks: view

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


event SetKilled:
    is_killed: bool


struct UserTicks:
    ns: int256  # packs n1 and n2, each is int128
    ticks: uint256[MAX_TICKS_INT // 2]  # Share fractions packed 2 per slot


MAX_TICKS_UINT: constant(uint256) = 50
MAX_TICKS_INT: constant(int256) = 50
WEEK: constant(uint256) = 604800


AMM: public(immutable(ILLAMMA))
CRV: public(immutable(CRV20))
GAUGE_CONTROLLER: public(immutable(GaugeController))
MINTER: public(immutable(Minter))
LENDING_FACTORY: public(immutable(LendingFactory))
COLLATERAL_TOKEN: public(immutable(IERC20))

is_killed: public(bool)

collateral_per_share: public(HashMap[int256, uint256])

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
        amm: ILLAMMA,
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
    COLLATERAL_TOKEN = IERC20(staticcall amm.coins(1))

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

    is_killed: bool = self.is_killed
    if is_killed:
        rate = 0
        new_rate = 0

    # Transfers from/to AMM always happen after LM Callback calls, so this value is taken BEFORE the action
    total_collateral: uint256 = staticcall COLLATERAL_TOKEN.balanceOf(AMM.address) - staticcall AMM.admin_fees_y()
    delta_rpc: uint256 = 0

    if total_collateral > 0 and block.timestamp > I_rpc.t:  # XXX should we not loop when total_collateral == 0?
        extcall GAUGE_CONTROLLER.checkpoint_gauge(self)
        prev_week_time: uint256 = I_rpc.t
        week_time: uint256 = min(unsafe_div(prev_week_time + WEEK, WEEK) * WEEK, block.timestamp)

        for week_iter: uint256 in range(500):
            w: uint256 = staticcall GAUGE_CONTROLLER.gauge_relative_weight(self, prev_week_time)

            if prev_future_epoch >= prev_week_time and prev_future_epoch < week_time:
                # If we went across one or multiple epochs, apply the rate
                # of the first epoch until it ends, and then the rate of
                # the last epoch.
                # If more than one epoch is crossed - the gauge gets less,
                # but that'd mean it wasn't called for more than 1 year
                delta_rpc += unsafe_div(rate * w * unsafe_sub(prev_future_epoch, prev_week_time), total_collateral)
                rate = new_rate
                delta_rpc += unsafe_div(rate * w * unsafe_sub(week_time, prev_future_epoch), total_collateral)
            else:
                delta_rpc += unsafe_div(rate * w * unsafe_sub(week_time, prev_week_time), total_collateral)
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

    # * Record the collateral per share values
    # * Record integrals of rewards per share
    if not is_killed:
        I_rpc.t = block.timestamp
        I_rpc.rpc += delta_rpc
        self.I_rpc = I_rpc

    for i: int256 in range(MAX_TICKS_INT):
        if i == size:
            break
        _n: int256 = n_start + i

        old_cps: uint256 = self.collateral_per_share[_n]
        if len(collateral_per_share) > 0:
            self.collateral_per_share[_n] = collateral_per_share[i]

        I_rps: IntegralRPS = self.I_rps[_n]
        I_rps.rps += unsafe_div(old_cps * unsafe_sub(I_rpc.rpc, I_rps.rpc), 10**18)
        I_rps.rpc = I_rpc.rpc
        self.I_rps[_n] = I_rps


@internal
def _checkpoint_user_shares(user: address, n_start: int256, old_user_shares: DynArray[uint256, MAX_TICKS_UINT], size: int256):
    """
    @notice Checkpoint for user's shares in a set of bands
    @dev Updates the CRV emissions a user is entitled to receive
    @param user The address of the user
    @param n_start Index of the first band to checkpoint
    @param user_shares User's shares by bands
    @param size The number of bands to checkpoint starting from `n_start`
    """
    rpu: uint256 = self.integrate_fraction[user]
    for i: int256 in range(MAX_TICKS_INT):
        if i == size:
            break
        _n: int256 = n_start + i

        old_user_shares_i: uint256 = 0
        if len(old_user_shares) > 0:
            old_user_shares_i = old_user_shares[i]

        I_rpu: IntegralRPU = self.I_rpu[user][_n]
        I_rps: uint256 = self.I_rps[_n].rps
        d_rpu: uint256 = unsafe_div(old_user_shares_i * unsafe_sub(I_rps, I_rpu.rps), 10**18)
        I_rpu.rpu += d_rpu
        I_rpu.rps = I_rps
        self.I_rpu[user][_n] = I_rpu
        rpu += d_rpu

    self.integrate_fraction[user] = rpu


@internal
@view
def _read_user_shares(user_shares_packed: UserTicks) -> DynArray[uint256, MAX_TICKS_UINT]:
    """
    @notice Unpacks and reads user ticks (shares) for all the ticks user deposited into
    @param user_shares_packed Packed user shares from AMM
    @return Array of shares the user has
    """
    ns: int256 = user_shares_packed.ns
    n2: int256 = unsafe_div(ns, 2 ** 128)
    n1: int256 = ns % 2 ** 128
    if n1 >= 2 ** 127:
        n1 = unsafe_sub(n1, 2 ** 128)
        n2 = unsafe_add(n2, 1)

    user_shares: DynArray[uint256, MAX_TICKS_UINT] = []
    size: uint256 = convert(n2 - n1 + 1, uint256)
    for i: int256 in range(MAX_TICKS_INT // 2):
        if len(user_shares) == size:
            break
        tick: uint256 = user_shares_packed.ticks[i]
        user_shares.append(tick & (2**128 - 1))
        if len(user_shares) == size:
            break
        user_shares.append(shift(tick, -128))

    return user_shares


@external
@view
def total_collateral() -> uint256:
    """
    @return Total collateral amount in LlamaLend/crvUSD AMM
    """
    return staticcall COLLATERAL_TOKEN.balanceOf(AMM.address) - staticcall AMM.admin_fees_y()


@external
@view
def user_collateral(user: address) -> uint256:
    """
    @param user The address of the user
    @return User's collateral amount in LlamaLend/crvUSD AMM
    """
    return (staticcall AMM.get_sum_xy(user))[1]


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
    assert msg.sender == AMM.address
    self._checkpoint_collateral_shares(n_start, collateral_per_share, convert(size, int256))


@external
def callback_user_shares(user: address, n_start: int256, old_user_shares: DynArray[uint256, MAX_TICKS_UINT], size: uint256):
    """
    @notice Checkpoint for user's shares in a set of bands.
    @dev Updates the CRV emissions a user is entitled to receive.
         Can be called only be the corresponding AMM.
    @param user The address of the user
    @param n_start Index of the first band to checkpoint
    @param old_user_shares User's shares by bands taken BEFORE the action
    """
    assert msg.sender == AMM.address
    self._checkpoint_user_shares(user, n_start, old_user_shares, convert(size, int256))


@external
def user_checkpoint(addr: address) -> bool:
    """
    @notice Record a checkpoint for `addr`
    @param addr User address
    @return bool success
    """
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(addr)
    user_shares: DynArray[uint256, MAX_TICKS_UINT] = self._read_user_shares(staticcall AMM.user_shares(addr))
    self._checkpoint_collateral_shares(ns[0], [], ns[1] - ns[0] + 1)
    if len(user_shares) > 0 and user_shares[0] > 0:
        self._checkpoint_user_shares(addr, ns[0], user_shares, ns[1] - ns[0] + 1)

    return True


@external
def claimable_tokens(addr: address) -> uint256:
    """
    @notice Get the number of claimable tokens per user
    @dev This function should be manually changed to "view" in the ABI
    @param addr User address
    @return uint256 number of claimable tokens per user
    """
    ns: int256[2] = staticcall AMM.read_user_tick_numbers(addr)
    user_shares: DynArray[uint256, MAX_TICKS_UINT] = self._read_user_shares(staticcall AMM.user_shares(addr))
    self._checkpoint_collateral_shares(ns[0], [], ns[1] - ns[0] + 1)
    if len(user_shares) > 0 and user_shares[0] > 0:
        self._checkpoint_user_shares(addr, ns[0], user_shares, ns[1] - ns[0] + 1)

    return self.integrate_fraction[addr] - staticcall MINTER.minted(addr, self)


@external
def set_killed(_is_killed: bool):
    """
    @notice Set the killed status for this contract
    @dev When killed, the gauge always yields a rate of 0 and so cannot mint CRV
    @param _is_killed Killed status to set
    """
    assert msg.sender == staticcall LENDING_FACTORY.admin()  # dev: only owner
    self._checkpoint_collateral_shares(0, [], 0)
    self.is_killed = _is_killed
    log SetKilled(is_killed=_is_killed)
