# @version 0.3.7
"""
WARNING:
At the moment this contract is unfinished, so not recommended to be used
without understanding.
"""
from vyper.interfaces import ERC20

interface Factory:
    def get_amm(collateral: address, i: uint256) -> address: view

interface LLAMMA:
    def coins(i: uint256) -> address: view

interface VotingEscrowBoost:
    def adjusted_balance_of(_account: address) -> uint256: view

interface CRV20:
    def future_epoch_time_write() -> uint256: nonpayable
    def rate() -> uint256: view

event UpdateBoost:
    user: indexed(address)
    boost: uint256

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


MAX_TICKS_UINT: constant(uint256) = 50
MAX_TICKS_INT: constant(int256) = 50
TOKENLESS_PRODUCTION: constant(uint256) = 40
WEEK: constant(uint256) = 604800

amm: public(address)

FACTORY: immutable(Factory)
COLLATERAL_TOKEN: public(immutable(ERC20))
COLLATERAL_INDEX: public(immutable(uint256))
VECRV: public(immutable(ERC20))
CRV: public(immutable(CRV20))
VEBOOST_PROXY: public(immutable(VotingEscrowBoost))
GAUGE_CONTROLLER: public(immutable(GaugeController))
MINTER: public(immutable(Minter))

collateral_for_boost: public(HashMap[address, uint256])
total_collateral_for_boost: public(uint256)
working_supply: public(uint256)
working_balances: public(HashMap[address, uint256])

boosted_collateral: public(uint256)
collateral_per_share: public(HashMap[int256, uint256])
shares_per_band: public(HashMap[int256, uint256])  # This only counts staked shares

boosted_shares: public(HashMap[address, HashMap[int256, uint256]])
user_band: public(HashMap[address,int256])
user_range_size: public(HashMap[address,uint256])

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
def __init__(factory: Factory, collateral: ERC20, c_index: uint256,
             crv: CRV20, vecrv: ERC20, veboost_proxy: VotingEscrowBoost, gc: GaugeController, minter: Minter):
    # Init is done by deployer but the contract starts operating after creation of the market
    # The actual initialization is done by the vote which creates the market just before
    FACTORY = factory
    COLLATERAL_TOKEN = collateral
    COLLATERAL_INDEX = c_index
    VECRV = vecrv
    VEBOOST_PROXY = veboost_proxy
    CRV = crv
    GAUGE_CONTROLLER = gc
    MINTER = minter


@external
def initialize():
    amm: address = FACTORY.get_amm(COLLATERAL_TOKEN.address, COLLATERAL_INDEX)
    self.amm = amm
    assert COLLATERAL_TOKEN == ERC20(LLAMMA(amm).coins(1))
    self.inflation_rate = CRV.rate()
    self.future_epoch_time = CRV.future_epoch_time_write()


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


@internal
def _checkpoint_collateral_shares(n: int256, collateral_per_share: DynArray[uint256, MAX_TICKS_UINT], size: uint256):
    n_shares: int256 = 0
    if len(collateral_per_share) == 0:
        n_shares = convert(size, int256)
    else:
        n_shares = convert(len(collateral_per_share), int256)

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
    boosted_collateral: uint256 = self.boosted_collateral
    delta_rpc: uint256 = 0

    if boosted_collateral > 0 and block.timestamp > I_rpc.t:  # XXX should we not loop when boosted collateral == 0?
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
                delta_rpc += rate * w * (prev_future_epoch - prev_week_time) / boosted_collateral
                rate = new_rate
                delta_rpc += rate * w * (week_time - prev_future_epoch) / boosted_collateral
            else:
                delta_rpc += rate * w * dt / boosted_collateral

            if week_time == block.timestamp:
                break
            prev_week_time = week_time
            week_time = min(week_time + WEEK, block.timestamp)

        I_rpc.t = block.timestamp
        I_rpc.rpc += delta_rpc
        self.I_rpc = I_rpc

        # Update boosted_collateral
        for i in range(MAX_TICKS_INT):
            _n: int256 = n + i
            old_cps: uint256 = self.collateral_per_share[_n]
            cps: uint256 = old_cps
            if len(collateral_per_share) == 0:
                cps = old_cps
            else:
                cps = collateral_per_share[i]
                self.collateral_per_share[_n] = cps
            I_rps: IntegralRPS = self.I_rps[_n]
            I_rps.rps += old_cps * (I_rpc.rpc - I_rps.rpc) / 10**18
            I_rps.rpc = I_rpc.rpc
            self.I_rps[_n] = I_rps
            if cps != old_cps:
                spb: uint256 = self.shares_per_band[_n]
                if spb > 0:
                    # boosted_collateral += spb * (cps - old_cps) / 10**18
                    old_value: uint256 = spb * old_cps / 10**18
                    boosted_collateral = max(boosted_collateral + spb * cps / 10**18, old_value) - old_value
            if i == n_shares:
                break

        self.boosted_collateral = boosted_collateral


@external
def callback_collateral_shares(n: int256, collateral_per_share: DynArray[uint256, MAX_TICKS_UINT]):
    # It is important that this callback is called every time before callback_user_shares
    assert msg.sender == self.amm
    self._checkpoint_collateral_shares(n, collateral_per_share, 0)


@internal
def _checkpoint_user_shares(user: address, n: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT], size: uint256):
    boosted_collateral: uint256 = self.boosted_collateral

    # Calculate the amount of real collateral for the user
    n_shares: int256 = 0
    if len(user_shares) == 0:
        n_shares = convert(size, int256)
    else:
        n_shares = convert(len(user_shares), int256)

    collateral_amount: uint256 = 0
    user_cps: DynArray[uint256, MAX_TICKS_UINT] = []
    for i in range(MAX_TICKS_INT):
        if i == n_shares:
            break
        cps: uint256 = self.collateral_per_share[n + i]
        user_cps.append(cps)
        if len(user_shares) > 0:
            collateral_amount += user_shares[i] * cps / 10**18
    if len(user_shares) == 0:
        collateral_amount = self.collateral_for_boost[user]

    boost: uint256 = self._update_boost(user, collateral_amount)
    rpu: uint256 = self.integrate_fraction[user]

    for j in range(MAX_TICKS_INT):
        i: int256 = n + j
        if j == n_shares:
            break
        old_s: uint256 = self.boosted_shares[user][i]
        cps: uint256 = user_cps[j]
        s: uint256 = old_s
        if len(user_shares) > 0:
            s = user_shares[j] * boost / 10**18
            self.boosted_shares[user][i] = s

        I_rpu: IntegralRPU = self.I_rpu[user][i]
        I_rps: uint256 = self.I_rps[i].rps
        d_rpu: uint256 = old_s * (I_rps - I_rpu.rps) / 10**18
        I_rpu.rpu += d_rpu
        rpu += d_rpu
        I_rpu.rps = I_rps
        self.I_rpu[user][i] = I_rpu

        if s != old_s:
            self.shares_per_band[i] = self.shares_per_band[i] + s - old_s
            # boosted_collateral += cps * (s - old_s) / 10**18
            old_value: uint256 = cps * old_s / 10**18
            boosted_collateral = max(boosted_collateral + cps * s / 10**18, old_value) - old_value

    self.boosted_collateral = boosted_collateral
    self.integrate_fraction[user] = rpu


@external
def callback_user_shares(user: address, n: int256, user_shares: DynArray[uint256, MAX_TICKS_UINT]):
    assert msg.sender == self.amm
    self.user_band[user] = n
    self.user_range_size[user] = len(user_shares)
    self._checkpoint_user_shares(user, n, user_shares, 0)


@external
def user_checkpoint(addr: address) -> bool:
    """
    @notice Record a checkpoint for `addr`
    @param addr User address
    @return bool success
    """
    assert self.amm != empty(address)  # dev: not initialized
    assert msg.sender in [addr, MINTER.address]  # dev: unauthorized
    n: int256 = self.user_band[addr]
    size: uint256 = self.user_range_size[addr]
    self._checkpoint_collateral_shares(n, [], size)
    self._checkpoint_user_shares(addr, n, [], size)
    return True


@external
def claimable_tokens(addr: address) -> uint256:
    """
    @notice Get the number of claimable tokens per user
    @dev This function should be manually changed to "view" in the ABI
    @return uint256 number of claimable tokens per user
    """
    assert self.amm != empty(address)  # dev: not initialized
    n: int256 = self.user_band[addr]
    size: uint256 = self.user_range_size[addr]
    self._checkpoint_collateral_shares(n, [], size)
    self._checkpoint_user_shares(addr, n, [], size)
    return self.integrate_fraction[addr] - MINTER.minted(addr, self)
