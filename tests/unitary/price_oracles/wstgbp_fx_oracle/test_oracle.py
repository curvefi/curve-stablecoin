import boa
import boa_solidity
import pytest
import solcx

from tests.unitary.price_oracles.chainlink_ema.conftest import (
    CHAINLINK_EMA_DEPLOYER,
    FEED_DEPLOYER,
)


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
pip: public(address)
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
fx: public(uint256)
fail: public(bool)

@deploy
def __init__(feed_: address):
    self.chainlinkFeed = feed_
    self.fx = 13 * 10**17

@external
def set_price(x: uint256):
    self.fx = x

@external
def set_fail(x: bool):
    self.fail = x

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
    return self.fx

@external
def price_w() -> uint256:
    assert not self.fail
    return self.fx
"""
)


@pytest.fixture
def market():
    with boa.env.anchor():
        solcx.set_solc_version("0.8.25")
        pip = PIP.deploy()
        gem = GEM.deploy()
        wrapper = WRAPPER.deploy(pip.address, gem.address)
        feed = FEED.deploy()
        ema = EMA.deploy(feed.address)
        oracle = boa.load_partial_solc(ORACLE_SRC).deploy(
            wrapper.address, feed.address, ema.address
        )
        yield oracle, pip, wrapper, feed, ema


def test_nav_cap_downside_and_fx_leg(market):
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


def test_freeze_recovery_and_zero_nav(market):
    oracle, pip, wrapper, feed, ema = market
    held = oracle.price_w()

    boa.env.time_travel(seconds=30 * 3600 + 1)
    assert oracle.frozen() and oracle.fxFrozen()
    assert oracle.price() == oracle.price_w() == held
    feed.set_round(130000000, boa.env.evm.patch.timestamp)
    assert oracle.price() == oracle.price_w() == held

    ema.set_fail(True)
    assert oracle.price() == oracle.price_w() == held
    ema.set_fail(False)
    wrapper.set_quote(0)
    assert oracle.price() == oracle.price_w() == 1
    pip.set_value(0)
    assert oracle.frozen()
    assert oracle.price() == oracle.price_w() == 1


@pytest.mark.parametrize("bad_answer", [0, -1, 10**27])
def test_bad_chainlink_round_freezes(market, bad_answer):
    oracle, _, _, feed, _ = market
    held = oracle.price_w()
    feed.set_round(bad_answer, boa.env.evm.patch.timestamp)
    assert oracle.fxFrozen()
    assert oracle.price() == oracle.price_w() == held


def test_future_or_reverting_round_freezes(market):
    oracle, _, _, feed, _ = market
    held = oracle.price_w()
    feed.set_round(130000000, boa.env.evm.patch.timestamp + 1)
    assert oracle.price() == oracle.price_w() == held
    feed.set_fail(True)
    assert oracle.price() == oracle.price_w() == held


def test_real_chainlink_ema_smooths_fx_round():
    with boa.env.anchor():
        solcx.set_solc_version("0.8.25")
        pip = PIP.deploy()
        gem = GEM.deploy()
        wrapper = WRAPPER.deploy(pip.address, gem.address)
        feed = FEED_DEPLOYER.deploy(8)
        now = boa.env.evm.patch.timestamp
        feed.add_rounds(1, 130000000, now - 7200, 600, 12)
        ema = CHAINLINK_EMA_DEPLOYER.deploy(feed.address, 20, 30)
        oracle = boa.load_partial_solc(ORACLE_SRC).deploy(
            wrapper.address, feed.address, ema.address
        )
        old_price = oracle.price_w()

        feed.add_rounds(1, 140000000, now, 1, 1)
        boa.env.time_travel(seconds=31)
        smoothed = oracle.price()
        assert old_price < smoothed < 14 * 10**17
        assert oracle.price_w() == oracle.price() == smoothed
