import boa
import boa_solidity
import solcx
from eth.exceptions import Revert
import pytest

from tests.unitary.price_oracles.chainlink_ema.conftest import (
    CHAINLINK_EMA_DEPLOYER,
    FEED_DEPLOYER,
)


solcx.set_solc_version("0.8.25")

WAD = 10**18
ORACLE_SRC = "curve_stablecoin/price_oracles/v2/WstGBPFxOracle.sol"

GEM = boa.loads_partial(
    """
# pragma version 0.4.3
@external
@pure
def decimals() -> uint8:
    return 18
"""
)

FEES = boa.loads_partial(
    """
# pragma version 0.4.3
fee_bps: public(uint256)
fail: public(bool)

@external
def set_fee(x: uint256):
    self.fee_bps = x

@external
def set_fail(x: bool):
    self.fail = x

@external
@view
def burncost(nav: uint256) -> uint256:
    assert not self.fail
    # Matches the wrapper's fee module: round redemption quotes up.
    return (nav * (10000 - self.fee_bps) + 9999) // 10000
"""
)

WRAPPER = boa.loads_partial(
    """
# pragma version 0.4.3

gem: public(address)
act: public(address)
nav: uint256
nav_fail: bool

@deploy
def __init__(gem_: address, act_: address):
    self.gem = gem_
    self.act = act_
    self.nav = 10**18

@external
def set_nav(x: uint256):
    self.nav = x

@external
def set_nav_fail(x: bool):
    self.nav_fail = x

@external
@pure
def decimals() -> uint8:
    return 18

@external
@view
def navprice() -> uint256:
    assert not self.nav_fail
    return self.nav
"""
)

FEED = boa.loads_partial(
    """
# pragma version 0.4.3
answer: public(int256)
updated_at: public(uint256)
fail: public(bool)

@deploy
def __init__():
    self.answer = 130000000
    self.updated_at = block.timestamp

@external
def set_round(answer_: int256, updated_at_: uint256):
    self.answer = answer_
    self.updated_at = updated_at_

@external
def set_fail(x: bool):
    self.fail = x

@external
@pure
def decimals() -> uint8:
    return 8

@external
@view
def latestRoundData() -> (uint80, int256, uint256, uint256, uint80):
    assert not self.fail
    return 1, self.answer, self.updated_at, self.updated_at, 1
"""
)

EMA = boa.loads_partial(
    """
# pragma version 0.4.3
chainlinkFeed: public(address)
gbp_usd_rate: public(uint256)
fail: public(bool)
write_fail: public(bool)

@deploy
def __init__(feed_: address):
    self.chainlinkFeed = feed_
    self.gbp_usd_rate = 13 * 10**17

@external
def set_price(x: uint256):
    self.gbp_usd_rate = x

@external
def set_fail(x: bool):
    self.fail = x

@external
def set_write_fail(x: bool):
    self.write_fail = x

@external
@view
def price() -> uint256:
    assert not self.fail
    return self.gbp_usd_rate

@external
def price_w() -> uint256:
    assert not self.fail and not self.write_fail
    return self.gbp_usd_rate
"""
)


@pytest.fixture
def fees():
    return FEES.deploy()


@pytest.fixture
def wrapper(fees):
    with boa.env.anchor():
        yield WRAPPER.deploy(GEM.deploy().address, fees.address)


@pytest.fixture
def market(wrapper):
    feed = FEED.deploy()
    ema = EMA.deploy(feed.address)
    oracle = boa.load_partial_solc(ORACLE_SRC).deploy(wrapper.address, ema.address)
    return oracle, wrapper, feed, ema


@pytest.fixture
def real_ema_market(wrapper):
    feed = FEED_DEPLOYER.deploy(8)
    feed.add_rounds(1, 130000000, boa.env.timestamp - 7200, 600, 12)
    ema = CHAINLINK_EMA_DEPLOYER.deploy(feed.address, 10, 60)
    oracle = boa.load_partial_solc(ORACLE_SRC).deploy(wrapper.address, ema.address)
    return oracle, wrapper, feed, ema


def test_nav_cap_downside_and_gbp_usd_leg(market):
    oracle, wrapper, feed, ema = market
    assert oracle.price() == oracle.price_w() == 13 * 10**17

    wrapper.set_nav(2 * WAD)
    assert oracle.price() == oracle.price_w() == 13 * 10**17
    boa.env.time_travel(seconds=86400)
    assert oracle.price() == oracle.price_w()
    assert oracle.navAnchor() == WAD + WAD * oracle.MAX_UPSIDE_SPEED() * 86400 // WAD
    assert oracle.price() == oracle.navAnchor() * ema.price() // WAD

    anchor = oracle.navAnchor()
    boa.env.time_travel(seconds=30 * 86400)
    feed.set_round(130000000, boa.env.evm.patch.timestamp)
    assert oracle.price() == oracle.price_w()
    assert oracle.navAnchor() == (
        anchor * (WAD + oracle.MAX_UPSIDE_SPEED() * 7 * 86400) // WAD
    )

    wrapper.set_nav(WAD // 2)
    assert oracle.price() == oracle.price_w() == 65 * 10**16
    assert oracle.navAnchor() == WAD // 2

    ema.set_price(14 * 10**17)
    feed.set_round(140000000, boa.env.evm.patch.timestamp)
    assert oracle.price() == oracle.price_w() == 7 * 10**17


def test_nav_pause_holds_redemption_rate_while_fx_keeps_updating(market, fees):
    oracle, wrapper, _, ema = market
    oracle.price_w()
    wrapper.set_nav(0)
    fees.set_fail(True)
    boa.env.time_travel(seconds=86400)
    assert oracle.navPaused()
    for rate in (14 * 10**17, 12 * 10**17):
        ema.set_price(rate)
        assert oracle.price() == oracle.price_w() == rate
        assert oracle.cachedRedemptionRate() == WAD
    assert oracle.navAnchor() == WAD
    fees.set_fail(False)
    wrapper.set_nav(WAD)
    assert not oracle.navPaused()
    assert oracle.price() == oracle.price_w() == 12 * 10**17


def test_fx_uses_adapter_without_reading_feed(market):
    oracle, wrapper, feed, ema = market
    feed.set_fail(True)
    wrapper.set_nav(WAD // 2)
    ema.set_price(14 * 10**17)
    assert oracle.price() == oracle.price_w() == 7 * 10**17


def test_paused_nav_does_not_hide_ema_read_failure(market):
    oracle, wrapper, _, ema = market
    wrapper.set_nav(0)
    ema.set_fail(True)
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts():
            entrypoint()


@pytest.mark.parametrize("source", ["nav", "fee", "ema"])
def test_failed_reads_revert(market, fees, source):
    oracle, wrapper, _, ema = market
    saved = (
        oracle.navAnchor(),
        oracle.cachedRedemptionRate(),
        oracle.cachedTimestamp(),
    )
    {
        "nav": wrapper.set_nav_fail,
        "fee": fees.set_fail,
        "ema": ema.set_fail,
    }[source](True)
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts():
            entrypoint()
    assert (
        oracle.navAnchor(),
        oracle.cachedRedemptionRate(),
        oracle.cachedTimestamp(),
    ) == saved


@pytest.mark.parametrize("paused", [False, True])
def test_failed_ema_write_reverts_atomically(market, paused):
    oracle, wrapper, _, ema = market
    saved = (
        oracle.navAnchor(),
        oracle.cachedRedemptionRate(),
        oracle.cachedTimestamp(),
    )
    boa.env.time_travel(seconds=60)
    if paused:
        wrapper.set_nav(0)
    else:
        wrapper.set_nav(WAD // 2)
    ema.set_price(14 * 10**17)
    ema.set_write_fail(True)
    expected_price = 14 * 10**17 if paused else 7 * 10**17
    assert oracle.price() == expected_price
    with boa.reverts():
        oracle.price_w()
    assert (
        oracle.navAnchor(),
        oracle.cachedRedemptionRate(),
        oracle.cachedTimestamp(),
    ) == saved
    ema.set_write_fail(False)
    assert oracle.price() == oracle.price_w() == expected_price
    assert oracle.navAnchor() == (WAD if paused else WAD // 2)


@pytest.mark.parametrize("source", ["wrapper", "fees", "ema"])
def test_malformed_reads_revert(market, fees, source):
    oracle, wrapper, _, ema = market
    target = {"wrapper": wrapper, "fees": fees, "ema": ema}[source]
    boa.env.set_code(target.address, bytes.fromhex("60006000f3"))
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts():
            entrypoint()


def test_constructor_rejects_unusable_initial_redemption_rate(market, fees):
    _, wrapper, _, ema = market
    deployer = boa.load_partial_solc(ORACLE_SRC)
    wrapper.set_nav(0)
    with pytest.raises(Revert, match="unusable initial price"):
        deployer.deploy(wrapper.address, ema.address)
    wrapper.set_nav(WAD)
    fees.set_fee(10000)
    with pytest.raises(Revert, match="unusable initial price"):
        deployer.deploy(wrapper.address, ema.address)


@pytest.mark.parametrize("paused", [False, True])
def test_real_chainlink_ema_smooths_gbp_usd_round(real_ema_market, paused):
    oracle, wrapper, feed, ema = real_ema_market
    if paused:
        wrapper.set_nav(0)
    old_price = oracle.price_w()
    for answer in (140000000, 120000000):
        feed.add_rounds(1, answer, boa.env.timestamp, 1, 1)
        boa.env.time_travel(seconds=61)
        smoothed = oracle.price()
        target = answer * 10**10
        assert min(old_price, target) < smoothed < max(old_price, target)
        assert oracle.price_w() == oracle.price() == smoothed
        assert ema.storedPrice() == smoothed
        old_price = smoothed


def test_old_chainlink_round_updates_price_instead_of_holding_older_cache(
    real_ema_market,
):
    oracle, wrapper, feed, _ = real_ema_market
    old_price = oracle.price()

    boa.env.time_travel(seconds=3600)
    feed.add_rounds(1, 140000000, boa.env.timestamp, 1, 1)
    boa.env.time_travel(seconds=31 * 3600)
    wrapper.set_nav(WAD // 2)

    # The latest FX round is 31 hours old; our cached valuation is 32 hours old.
    assert old_price == 13 * 10**17
    assert not oracle.navPaused()
    assert oracle.price() == oracle.price_w() == 7 * 10**17
    assert oracle.navAnchor() == WAD // 2


@pytest.mark.parametrize("answer", [0, -1])
def test_invalid_answer_reverts_through_real_adapter(real_ema_market, answer):
    oracle, _, feed, _ = real_ema_market
    feed.add_rounds(1, answer, boa.env.timestamp, 1, 1)
    boa.env.time_travel(seconds=61)
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts("DFM: Chainlink answer too low"):
            entrypoint()


def test_zero_redemption_rate_stays_zero_during_pause_and_recovers(market, fees):
    oracle, wrapper, _, _ = market
    anchor = oracle.navAnchor()
    fees.set_fee(10000)
    assert oracle.price() == oracle.price_w() == 1
    assert oracle.cachedRedemptionRate() == 0
    assert oracle.navAnchor() == anchor
    fees.set_fee(0)
    wrapper.set_nav(0)
    boa.env.time_travel(seconds=30 * 3600 + 1)
    assert oracle.navPaused()
    assert oracle.price() == oracle.price_w() == 1
    wrapper.set_nav(WAD)
    assert oracle.price() == oracle.price_w() == anchor * 13 // 10
    assert oracle.navAnchor() == anchor


def test_zero_redemption_rate_does_not_need_gbp_usd(market, fees):
    oracle, wrapper, feed, ema = market
    fees.set_fee(10000)
    feed.set_fail(True)
    ema.set_fail(True)
    assert oracle.price() == oracle.price_w() == 1


@pytest.mark.parametrize("fee", [25, 5000, 9999, 10000])
def test_fee_change_and_reversal_leave_nav_anchor_intact(market, fees, fee):
    oracle, wrapper, _, ema = market
    original_price = oracle.price()
    fees.set_fee(fee)
    net_rate = (WAD * (10000 - fee) + 9999) // 10000
    assert oracle.price() == oracle.price_w() == max(1, net_rate * ema.price() // WAD)
    assert oracle.navAnchor() == WAD
    assert oracle.cachedRedemptionRate() == net_rate

    # No time passes: removing the fee must recover without waiting for the cap.
    fees.set_fee(0)
    assert oracle.price() == oracle.price_w() == original_price
    assert oracle.navAnchor() == WAD


@pytest.mark.parametrize("fee", [25, 5000, 9999])
def test_constructor_anchors_nav_before_fees(market, fees, fee):
    _, wrapper, _, ema = market
    fees.set_fee(fee)
    oracle = boa.load_partial_solc(ORACLE_SRC).deploy(wrapper.address, ema.address)
    assert oracle.navAnchor() == WAD
    assert oracle.cachedRedemptionRate() == fees.burncost(WAD)
    fees.set_fee(0)
    assert oracle.price() == oracle.price_w() == 13 * 10**17


@pytest.mark.parametrize("fee", [25, 5000, 9999, 10000])
def test_nav_growth_is_capped_before_applying_fees(market, fees, fee):
    oracle, wrapper, _, ema = market
    wrapper.set_nav(2 * WAD)
    fees.set_fee(fee)
    boa.env.time_travel(seconds=61)
    capped_nav = WAD + WAD * oracle.MAX_UPSIDE_SPEED() * 61 // WAD
    # Match the fee module's upward rounding, including fractional base units.
    expected_net = (capped_nav * (10000 - fee) + 9999) // 10000
    assert (
        oracle.price() == oracle.price_w() == max(1, expected_net * ema.price() // WAD)
    )
    assert oracle.navAnchor() == capped_nav
    assert oracle.cachedRedemptionRate() == expected_net
    assert expected_net <= fees.burncost(2 * WAD)


@pytest.mark.parametrize("fee", [0, 10000])
def test_nav_loss_and_recovery_are_capped_even_with_zero_net_quote(market, fees, fee):
    oracle, wrapper, _, ema = market
    wrapper.set_nav(WAD // 2)
    fees.set_fee(fee)
    expected = 1 if fee == 10000 else 65 * 10**16
    assert oracle.price() == oracle.price_w() == expected
    assert oracle.navAnchor() == WAD // 2

    wrapper.set_nav(WAD)
    fees.set_fee(0)
    assert oracle.price() == 65 * 10**16
    boa.env.time_travel(seconds=86400)
    cap = (WAD // 2) * (WAD + oracle.MAX_UPSIDE_SPEED() * 86400) // WAD
    assert oracle.price() == oracle.price_w() == cap * ema.price() // WAD


def test_fee_changes_during_pause_preserve_cached_net_quote(market, fees):
    oracle, wrapper, _, ema = market
    fees.set_fee(5000)
    oracle.price_w()
    wrapper.set_nav(0)
    fees.set_fee(10000)
    ema.set_price(14 * 10**17)
    assert oracle.price() == oracle.price_w() == 7 * 10**17
    assert oracle.cachedRedemptionRate() == WAD // 2
    assert oracle.navAnchor() == WAD

    wrapper.set_nav(WAD)
    assert oracle.price() == oracle.price_w() == 1
    fees.set_fee(0)
    assert oracle.price() == oracle.price_w() == 14 * 10**17
