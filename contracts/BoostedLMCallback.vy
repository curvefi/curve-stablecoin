# @version 0.3.10
"""
@title LlamaLend LMCallback
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
@notice LM callback works like a gauge for collateral in LlamaLend/crvUSD AMMs
"""

from vyper.interfaces import ERC20

interface LLAMMA:
    def coins(i: uint256) -> address: view
    def bands_x(n: int256) -> uint256: view

interface VotingEscrowBoost:
    def adjusted_balance_of(_account: address) -> uint256: view

interface CRV20:
    def future_epoch_time_write() -> uint256: nonpayable
    def rate() -> uint256: view

interface GaugeController:
    def period() -> int128: view
    def period_write() -> int128: nonpayable
    def period_timestamp(p: int128) -> uint256: view
    def gauge_relative_weight(addr: address, time: uint256) -> uint256: view
    def voting_escrow() -> address: view
    def checkpoint(): nonpayable
    def checkpoint_gauge(addr: address): nonpayable

interface Minter:
    def token() -> address: view
    def controller() -> address: view
    def minted(user: address, gauge: address) -> uint256: view


event UpdateLiquidityLimit:
    user: indexed(address)
    original_balance: uint256
    original_supply: uint256
    working_balance: uint256
    working_supply: uint256


MAX_TICKS_UINT: constant(uint256) = 50
MAX_TICKS_INT: constant(int256) = 50
TOKENLESS_PRODUCTION: constant(uint256) = 40
WEEK: constant(uint256) = 604800

AMM: public(immutable(LLAMMA))
VECRV: public(immutable(ERC20))
CRV: public(immutable(CRV20))
VEBOOST_PROXY: public(immutable(VotingEscrowBoost))
GAUGE_CONTROLLER: public(immutable(GaugeController))
MINTER: public(immutable(Minter))

total_collateral: public(uint256)
working_supply: public(uint256)
user_boost: public(HashMap[address, uint256])

collateral_per_share: public(HashMap[int256, uint256])
shares_per_band: public(HashMap[int256, uint256])
working_shares_per_band: public(HashMap[int256, uint256])  # This only counts staked shares

working_shares: public(HashMap[address, HashMap[int256, uint256]])
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


@external
def __init__(
        amm: LLAMMA,
        crv: CRV20,
        vecrv: ERC20,
        veboost_proxy: VotingEscrowBoost,
        gauge_controller: GaugeController,
        minter: Minter,
):
    """
    @notice LLAMMA constructor.
            Init is done by deployer but the contract starts operating after creation of the market.
            The actual initialization is done by the vote which creates the market just before.
    @param factory: LlamaLend/crvUSD factory address
    @param collateral: The address of collateral token
    @param c_index: The index of the market (among markets with the same collateral)
    @param crv: The address of CRV token
    @param vecrv: The address of veCRV
    @param veboost_proxy: The address of voting escrow proxy
    @param gc: The address of the gauge controller
    @param minter: the address of CRV minter
    """
    AMM = amm
    CRV = crv
    VECRV = vecrv
    VEBOOST_PROXY = veboost_proxy
    GAUGE_CONTROLLER = gauge_controller
    MINTER = minter

    self.inflation_rate = crv.rate()
    self.future_epoch_time = crv.future_epoch_time_write()


@internal
def _update_liquidity_limit(user: address, collateral_amount: uint256, old_collateral_amount: uint256, is_underwater: bool) -> uint256:
    """
    @notice Calculate limits which depend on the amount of CRV token per-user.
            Effectively it calculates working collateral to apply amplification
            of CRV production by CRV.
    @dev Updates `total_collateral`, `working_supply` and `user_boost`
    @param user The address of the user
    @param collateral_amount User's amount of collateral BEFORE the checkpoint
    @param old_collateral_amount User's amount of collateral AFTER the checkpoint
    @param is_underwater Whether soft-liquidation for user's position started or not
    @return User's boost: working_collateral / total_collateral [0.4, 1]
    """
    # collateral_amount and total are used to calculate boosts
    L: uint256 = max(self.total_collateral + collateral_amount, old_collateral_amount) - old_collateral_amount
    self.total_collateral = L

    boost: uint256 = self.user_boost[user]
    lim: uint256 = collateral_amount * boost / 10 ** 18
    if not is_underwater:
        # To be called after totalSupply is updated
        voting_balance: uint256 = VEBOOST_PROXY.adjusted_balance_of(user)
        voting_total: uint256 = VECRV.totalSupply()

        lim = collateral_amount * TOKENLESS_PRODUCTION / 100
        if voting_total > 0:
            lim += L * voting_balance / voting_total * (100 - TOKENLESS_PRODUCTION) / 100
        lim = min(collateral_amount, lim)

    _working_supply: uint256 = self.working_supply + lim - old_collateral_amount * self.user_boost[user] / 10**18
    self.working_supply = _working_supply
    if collateral_amount > 0 and not is_underwater:  # Do not update boost for underwater user to prevent manipulation
        boost = lim * 10**18 / collateral_amount
        self.user_boost[user] = boost

    log UpdateLiquidityLimit(user, collateral_amount, L, lim, _working_supply)

    return boost


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
    if prev_future_epoch >= I_rpc.t:
        self.future_epoch_time = CRV.future_epoch_time_write()
        new_rate = CRV.rate()
        self.inflation_rate = new_rate

    # * Record the collateral per share values
    # * Record integrals of rewards per share
    working_supply: uint256 = self.working_supply
    total_collateral: uint256 = self.total_collateral
    delta_rpc: uint256 = 0

    if working_supply > 0 and block.timestamp > I_rpc.t:  # XXX should we not loop when boosted collateral == 0?
        GAUGE_CONTROLLER.checkpoint_gauge(self)
        prev_week_time: uint256 = I_rpc.t
        week_time: uint256 = min((I_rpc.t + WEEK) / WEEK * WEEK, block.timestamp)

        for week_iter in range(500):
            dt: uint256 = week_time - prev_week_time
            w: uint256 = GAUGE_CONTROLLER.gauge_relative_weight(self, prev_week_time / WEEK * WEEK)

            if prev_future_epoch >= prev_week_time and prev_future_epoch < week_time:
                # If we went across one or multiple epochs, apply the rate
                # of the first epoch until it ends, and then the rate of
                # the last epoch.
                # If more than one epoch is crossed - the gauge gets less,
                # but that'd mean it wasn't called for more than 1 year
                delta_rpc += rate * w * (prev_future_epoch - prev_week_time) / working_supply
                rate = new_rate
                delta_rpc += rate * w * (week_time - prev_future_epoch) / working_supply
            else:
                delta_rpc += rate * w * dt / working_supply
            # On precisions of the calculation
            # rate ~= 10e18
            # last_weight > 0.01 * 1e18 = 1e16 (if pool weight is 1%)
            # _working_supply ~= TVL * 1e18 ~= 1e26 ($100M for example)
            # The largest loss is at dt = 1
            # Loss is 1e-9 - acceptable

            if week_time == block.timestamp:
                break
            prev_week_time = week_time
            week_time = min(week_time + WEEK, block.timestamp)

    I_rpc.t = block.timestamp
    I_rpc.rpc += delta_rpc
    self.I_rpc = I_rpc

    # Update working_supply
    for i in range(MAX_TICKS_INT):
        if i == size:
            break
        _n: int256 = n_start + i
        old_cps: uint256 = self.collateral_per_share[_n]
        cps: uint256 = old_cps
        if len(collateral_per_share) > 0:
            cps = collateral_per_share[i]
            self.collateral_per_share[_n] = cps
        I_rps: IntegralRPS = self.I_rps[_n]
        I_rps.rps += old_cps * (I_rpc.rpc - I_rps.rpc) / 10**18
        I_rps.rpc = I_rpc.rpc
        self.I_rps[_n] = I_rps
        if cps != old_cps:
            wspb: uint256 = self.working_shares_per_band[_n]
            spb: uint256 = self.shares_per_band[_n]
            if wspb > 0:
                # working_supply += wspb * (cps - old_cps) / 10**18
                old_working_supply: uint256 = wspb * old_cps / 10**18
                working_supply = max(working_supply + wspb * cps / 10**18, old_working_supply) - old_working_supply
                old_total_collateral: uint256 = spb * old_cps / 10 ** 18
                total_collateral = max(total_collateral + spb * cps / 10**18, old_total_collateral) - old_total_collateral

    self.working_supply = working_supply
    self.total_collateral = total_collateral


@internal
@view
def _user_amounts(user: address, n_start: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT], size: int256) -> uint256[3]:
    """
    @notice Calculates user collateral amount from user bands and shares
    @param user: The address of the user
    @param n_start Index of the first band to checkpoint
    @param user_shares User's shares by bands
    @param size The number of bands to checkpoint starting from `n_start`
    @return: [
                collateral_amount calculated from passed args,
                old_collateral_amount,
                stablecoin_amount (needed to check whether user is underwater or not),
             ]
    """
    old_collateral_amount: uint256 = 0
    collateral_amount: uint256 = 0
    stablecoin_amount: uint256 = 0  # this amount is needed just to check whether user is_underwater or not
    if len(user_shares) > 0:
        for i in range(MAX_TICKS_INT):
            if i == size:
                break
            cps: uint256 = self.collateral_per_share[n_start + i]
            old_collateral_amount += self.user_shares[user][n_start + i] * cps / 10**18
            collateral_amount += user_shares[i] * cps / 10**18
            stablecoin_amount += AMM.bands_x(n_start + i)

        return [collateral_amount, old_collateral_amount, stablecoin_amount]
    else:
        for i in range(MAX_TICKS_INT):
            if i == size:
                break
            old_collateral_amount += self.user_shares[user][n_start + i] * self.collateral_per_share[n_start + i] / 10**18
            stablecoin_amount += AMM.bands_x(n_start + i)

        return [old_collateral_amount, old_collateral_amount, stablecoin_amount]


@internal
def _checkpoint_user_shares(user: address, n_start: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT], size: int256):
    """
    @notice Checkpoint for user's shares in a set of bands
    @dev Updates the CRV emissions a user is entitled to receive
    @param user: The address of the user
    @param n_start Index of the first band to checkpoint
    @param user_shares User's shares by bands
    @param size The number of bands to checkpoint starting from `n_start`
    """
    # Calculate the amount of real collateral for the user
    _amounts: uint256[3] = self._user_amounts(user, n_start, user_shares, size)  # [collateral_amount, old_collateral_amount]
    boost: uint256 = self._update_liquidity_limit(user, _amounts[0], _amounts[1], _amounts[2] > 0)

    rpu: uint256 = self.integrate_fraction[user]

    for i in range(MAX_TICKS_INT):
        if i == size:
            break
        _n: int256 = n_start + i
        old_ws: uint256 = self.working_shares[user][_n]

        if len(user_shares) > 0:
            # Transition from working_balance to working_shares:
            # 1. working_balance * real_shares == real_balance * working_shares
            # 2. collateral_per_share * working_shares = working_balance
            #
            # It's needed to update working supply during soft-liquidation
            self.shares_per_band[_n] = self.shares_per_band[_n] + user_shares[i] - self.user_shares[user][_n]
            self.user_shares[user][_n] = user_shares[i]

            ws: uint256 = user_shares[i] * boost / 10**18
            self.working_shares[user][_n] = ws
            self.working_shares_per_band[_n] = self.working_shares_per_band[_n] + ws - old_ws
        else:  # Here we just update boost
            ws: uint256 = self.user_shares[user][_n] * boost / 10**18
            self.working_shares[user][_n] = ws
            self.working_shares_per_band[_n] = self.working_shares_per_band[_n] + ws - old_ws


        I_rpu: IntegralRPU = self.I_rpu[user][_n]
        I_rps: uint256 = self.I_rps[_n].rps
        d_rpu: uint256 = old_ws * (I_rps - I_rpu.rps) / 10**18
        I_rpu.rpu += d_rpu
        rpu += d_rpu
        I_rpu.rps = I_rps
        self.I_rpu[user][_n] = I_rpu

    self.integrate_fraction[user] = rpu


@external
@view
def user_collateral(user: address) -> uint256:
    """
    @param user: The address of the user
    @return: User's collateral amount in LlamaLend/crvUSD AMM
    """
    return self._user_amounts(user, self.user_start_band[user], [], self.user_range_size[user])[0]


@external
@view
def working_collateral(user: address) -> uint256:
    """
    @param user: The address of the user
    @return: User's working collateral amount [0.4 * user_collateral, user_collateral]
    """
    n_start: int256 = self.user_start_band[user]
    size: int256 = self.user_range_size[user]
    _working_balance: uint256 = 0
    for i in range(MAX_TICKS_INT):
        if i == size:
            break
        _working_balance += self.working_shares[user][n_start + i] * self.collateral_per_share[n_start + i] / 10 ** 18

    return _working_balance


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
def callback_user_shares(user: address, n_start: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT]):
    """
    @notice Checkpoint for user's shares in a set of bands.
    @dev Updates the CRV emissions a user is entitled to receive.
         Can be called only be the corresponding AMM.
    @param user: The address of the user
    @param user_shares User's shares by bands
    """
    assert msg.sender == AMM.address
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
    assert msg.sender in [addr, MINTER.address]  # dev: unauthorized
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
    @return uint256 number of claimable tokens per user
    """
    n_start: int256 = self.user_start_band[addr]
    size: int256 = self.user_range_size[addr]
    self._checkpoint_collateral_shares(n_start, [], size)
    self._checkpoint_user_shares(addr, n_start, [], size)

    return self.integrate_fraction[addr] - MINTER.minted(addr, self)
