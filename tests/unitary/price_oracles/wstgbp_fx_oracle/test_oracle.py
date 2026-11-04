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

PIP = boa.loads_partial(
    """
# pragma version 0.4.3
value: public(uint256)
fail: public(bool)

@deploy
def __init__():
    self.value = 1

@external
def set_value(x: uint256):
    self.value = x

@external
def set_fail(x: bool):
    self.fail = x

@external
@view
def read() -> uint256:
    assert not self.fail
    return self.value
"""
)

GEM = boa.loads_partial(
    """
# pragma version 0.4.3
@external
@pure
def decimals() -> uint8:
    return 18
"""
)

WRAPPER = boa.loads_partial(
    """
# pragma version 0.4.3

interface Pip:
    def read() -> uint256: view

pip: address
gem: public(address)
quote: public(uint256)
fail: public(bool)

@deploy
def __init__(pip_: address, gem_: address):
    self.pip = pip_
    self.gem = gem_
    self.quote = 10**18

@external
def set_quote(x: uint256):
    self.quote = x

@external
def set_fail(x: bool):
    self.fail = x

@external
@pure
def decimals() -> uint8:
    return 18

@external
@view
def navprice() -> uint256:
    return staticcall Pip(self.pip).read()

@external
@view
def burncost() -> uint256:
    assert not self.fail
    return self.quote
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
gbp_usd_price: public(uint256)
fail: public(bool)
write_fail: public(bool)

@deploy
def __init__(feed_: address):
    self.chainlinkFeed = feed_
    self.gbp_usd_price = 13 * 10**17

@external
def set_price(x: uint256):
    self.gbp_usd_price = x

@external
def set_fail(x: bool):
    self.fail = x

@external
def set_write_fail(x: bool):
    self.write_fail = x

@external
@pure
def OBSERVATIONS() -> uint256:
    return 20

@external
@pure
def INTERVAL() -> uint256:
    return 30

@external
@view
def price() -> uint256:
    assert not self.fail
    return self.gbp_usd_price

@external
def price_w() -> uint256:
    assert not self.fail and not self.write_fail
    return self.gbp_usd_price
"""
)


@pytest.fixture
def market():
    with boa.env.anchor():
        pip = PIP.deploy()
        gem = GEM.deploy()
        wrapper = WRAPPER.deploy(pip.address, gem.address)
        feed = FEED.deploy()
        ema = EMA.deploy(feed.address)
        oracle = boa.load_partial_solc(ORACLE_SRC).deploy(wrapper.address, ema.address)
        yield oracle, pip, wrapper, feed, ema


def test_nav_cap_downside_and_gbp_usd_leg(market):
    oracle, _, wrapper, feed, ema = market
    assert oracle.price() == oracle.price_w() == 13 * 10**17

    wrapper.set_quote(2 * WAD)
    assert oracle.price() == oracle.price_w() == 13 * 10**17
    boa.env.time_travel(seconds=86400)
    assert oracle.price() == oracle.price_w()
    assert oracle.cachedQuote() == WAD + WAD * oracle.MAX_UPSIDE_SPEED() * 86400 // WAD
    assert oracle.price() == oracle.cachedQuote() * ema.price() // WAD

    anchor = oracle.cachedQuote()
    boa.env.time_travel(seconds=30 * 86400)
    feed.set_round(130000000, boa.env.evm.patch.timestamp)
    assert oracle.price() == oracle.price_w()
    assert oracle.cachedQuote() == (
        anchor * (WAD + oracle.MAX_UPSIDE_SPEED() * 7 * 86400) // WAD
    )

    wrapper.set_quote(WAD // 2)
    assert oracle.price() == oracle.price_w() == 65 * 10**16
    assert oracle.cachedQuote() == WAD // 2

    ema.set_price(14 * 10**17)
    feed.set_round(140000000, boa.env.evm.patch.timestamp)
    assert oracle.price() == oracle.price_w() == 7 * 10**17


def test_nav_pause_holds_nav_while_fx_keeps_updating(market):
    oracle, pip, wrapper, _, ema = market
    oracle.price_w()
    wrapper.set_quote(2 * WAD)
    pip.set_value(0)
    wrapper.set_fail(True)
    boa.env.time_travel(seconds=86400)
    assert oracle.navPaused()
    for rate in (14 * 10**17, 12 * 10**17):
        ema.set_price(rate)
        assert oracle.price() == oracle.price_w() == rate
        assert oracle.cachedNav() == WAD
    assert oracle.cachedQuote() == WAD
    wrapper.set_fail(False)
    pip.set_value(1)
    assert not oracle.navPaused()
    assert oracle.price() == oracle.price_w() == 12 * 10**17


def test_fx_uses_adapter_without_reading_feed(market):
    oracle, _, wrapper, feed, ema = market
    feed.set_fail(True)
    wrapper.set_quote(WAD // 2)
    ema.set_price(14 * 10**17)
    assert oracle.price() == oracle.price_w() == 7 * 10**17


def test_paused_nav_does_not_hide_ema_read_failure(market):
    oracle, pip, _, _, ema = market
    pip.set_value(0)
    ema.set_fail(True)
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts():
            entrypoint()


@pytest.mark.parametrize("source", [1, 2, 4], ids=["pip", "wrapper", "ema"])
def test_failed_reads_revert(market, source):
    oracle = market[0]
    saved = oracle.cachedQuote(), oracle.cachedNav(), oracle.cachedTimestamp()
    market[source].set_fail(True)
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts():
            entrypoint()
    assert (
        oracle.cachedQuote(),
        oracle.cachedNav(),
        oracle.cachedTimestamp(),
    ) == saved


@pytest.mark.parametrize("paused", [False, True])
def test_failed_ema_write_reverts_atomically(market, paused):
    oracle, pip, wrapper, _, ema = market
    saved = oracle.cachedQuote(), oracle.cachedNav(), oracle.cachedTimestamp()
    boa.env.time_travel(seconds=60)
    if paused:
        pip.set_value(0)
    wrapper.set_quote(WAD // 2)
    ema.set_price(14 * 10**17)
    ema.set_write_fail(True)
    expected_price = 14 * 10**17 if paused else 7 * 10**17
    assert oracle.price() == expected_price
    with boa.reverts():
        oracle.price_w()
    assert (
        oracle.cachedQuote(),
        oracle.cachedNav(),
        oracle.cachedTimestamp(),
    ) == saved
    ema.set_write_fail(False)
    assert oracle.price() == oracle.price_w() == expected_price
    assert oracle.cachedQuote() == (WAD if paused else WAD // 2)


@pytest.mark.parametrize("source", [1, 2, 4], ids=["pip", "wrapper", "ema"])
def test_malformed_reads_revert(market, source):
    oracle = market[0]
    boa.env.set_code(market[source].address, bytes.fromhex("60006000f3"))
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts():
            entrypoint()


def test_constructor_rejects_unusable_initial_nav(market):
    _, pip, wrapper, _, ema = market
    deployer = boa.load_partial_solc(ORACLE_SRC)
    pip.set_value(0)
    with pytest.raises(Revert, match="unusable initial price"):
        deployer.deploy(wrapper.address, ema.address)
    pip.set_value(1)
    wrapper.set_quote(0)
    with pytest.raises(Revert, match="unusable initial price"):
        deployer.deploy(wrapper.address, ema.address)


@pytest.mark.parametrize("paused", [False, True])
def test_real_chainlink_ema_smooths_gbp_usd_round(paused):
    with boa.env.anchor():
        pip = PIP.deploy()
        gem = GEM.deploy()
        wrapper = WRAPPER.deploy(pip.address, gem.address)
        feed = FEED_DEPLOYER.deploy(8)
        now = boa.env.timestamp
        feed.add_rounds(1, 130000000, now - 7200, 600, 12)
        ema = CHAINLINK_EMA_DEPLOYER.deploy(feed.address, 20, 30)
        oracle = boa.load_partial_solc(ORACLE_SRC).deploy(wrapper.address, ema.address)
        if paused:
            pip.set_value(0)
            wrapper.set_quote(2 * WAD)
        old_price = oracle.price_w()
        for answer in (140000000, 120000000):
            feed.add_rounds(1, answer, boa.env.timestamp, 1, 1)
            boa.env.time_travel(seconds=31)
            smoothed = oracle.price()
            target = answer * 10**10
            assert min(old_price, target) < smoothed < max(old_price, target)
            assert oracle.price_w() == oracle.price() == smoothed
            assert ema.storedPrice() == smoothed
            old_price = smoothed


def test_old_chainlink_round_updates_price_instead_of_holding_older_cache():
    with boa.env.anchor():
        pip = PIP.deploy()
        gem = GEM.deploy()
        wrapper = WRAPPER.deploy(pip.address, gem.address)
        feed = FEED_DEPLOYER.deploy(8)
        feed.add_rounds(1, 130000000, boa.env.timestamp - 7200, 600, 12)
        ema = CHAINLINK_EMA_DEPLOYER.deploy(feed.address, 20, 30)
        oracle = boa.load_partial_solc(ORACLE_SRC).deploy(wrapper.address, ema.address)
        old_price = oracle.price()

        boa.env.time_travel(seconds=3600)
        feed.add_rounds(1, 140000000, boa.env.timestamp, 1, 1)
        boa.env.time_travel(seconds=31 * 3600)
        wrapper.set_quote(WAD // 2)

        # The latest FX round is 31 hours old; our cached valuation is 32 hours old.
        assert old_price == 13 * 10**17
        assert not oracle.navPaused()
        assert oracle.price() == oracle.price_w() == 7 * 10**17
        assert oracle.cachedQuote() == WAD // 2


@pytest.mark.parametrize("answer", [0, -1])
def test_invalid_answer_reverts_through_real_adapter(answer):
    with boa.env.anchor():
        pip = PIP.deploy()
        gem = GEM.deploy()
        wrapper = WRAPPER.deploy(pip.address, gem.address)
        feed = FEED_DEPLOYER.deploy(8)
        feed.add_rounds(1, 130000000, boa.env.timestamp - 7200, 600, 12)
        ema = CHAINLINK_EMA_DEPLOYER.deploy(feed.address, 20, 30)
        oracle = boa.load_partial_solc(ORACLE_SRC).deploy(wrapper.address, ema.address)
        feed.add_rounds(1, answer, boa.env.timestamp, 1, 1)
        boa.env.time_travel(seconds=31)
        for entrypoint in (oracle.price, oracle.price_w):
            with boa.reverts("DFM: Chainlink answer too low"):
                entrypoint()


def test_zero_nav_stays_zero_during_pause_and_recovers(market):
    oracle, pip, wrapper, _, _ = market
    anchor = oracle.cachedQuote()
    wrapper.set_quote(0)
    assert oracle.price() == oracle.price_w() == 1
    assert oracle.cachedNav() == 0
    assert oracle.cachedQuote() == anchor
    wrapper.set_quote(2 * WAD)
    pip.set_value(0)
    boa.env.time_travel(seconds=30 * 3600 + 1)
    assert oracle.navPaused()
    assert oracle.price() == oracle.price_w() == 1
    pip.set_value(1)
    assert oracle.price() == oracle.price_w() == anchor * 13 // 10
    assert oracle.cachedQuote() == anchor


def test_zero_nav_does_not_need_gbp_usd(market):
    oracle, _, wrapper, feed, ema = market
    wrapper.set_quote(0)
    feed.set_fail(True)
    ema.set_fail(True)
    assert oracle.price() == oracle.price_w() == 1
