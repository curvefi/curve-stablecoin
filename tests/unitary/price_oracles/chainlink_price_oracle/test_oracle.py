import boa
import pytest


SOURCE = "curve_stablecoin/price_oracles/v2/ChainlinkPriceOracle.vy"
MAX_AGE = 86400
FEED_DEPLOYER = boa.loads_partial("""
# pragma version 0.4.3
decimals: public(uint8)
answer: public(int256)
updated_at: public(uint256)
fail: public(bool)

@deploy
def __init__(decimals: uint8):
    self.decimals = decimals
    self.answer = convert(10**convert(decimals, uint256), int256)
    self.updated_at = block.timestamp

@external
def set_round(answer: int256, updated_at: uint256):
    self.answer = answer
    self.updated_at = updated_at

@external
def set_fail(fail: bool):
    self.fail = fail

@external
@view
def latestRoundData() -> (uint80, int256, uint256, uint256, uint80):
    assert not self.fail, "Feed unavailable"
    return 1, self.answer, self.updated_at, self.updated_at, 1
""")


@pytest.fixture
def market():
    with boa.env.anchor():
        feed = FEED_DEPLOYER.deploy(8)
        oracle = boa.load(SOURCE, feed.address, MAX_AGE)
        yield feed, oracle


@pytest.mark.parametrize("decimals", [0, 6, 8, 18])
def test_decimal_normalization(decimals):
    with boa.env.anchor():
        feed = FEED_DEPLOYER.deploy(decimals)
        oracle = boa.load(SOURCE, feed.address, MAX_AGE)
        assert oracle.price() == oracle.price_w() == 10**18


@pytest.mark.parametrize("answer", [87_000_000, 99_971_556, 100_000_000, 101_000_000])
def test_live_price_is_not_capped_or_smoothed(market, answer):
    feed, oracle = market
    feed.set_round(answer, boa.env.timestamp)
    assert oracle.price() == oracle.price_w() == answer * 10**10


@pytest.mark.parametrize("answer", [0, -1])
def test_invalid_answers_revert(market, answer):
    feed, oracle = market
    feed.set_round(answer, boa.env.timestamp)
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts("Invalid answer"):
            entrypoint()


@pytest.mark.parametrize("timestamp", [0, "future"])
def test_invalid_timestamps_revert(market, timestamp):
    feed, oracle = market
    feed.set_round(100_000_000, boa.env.timestamp + 1 if timestamp == "future" else 0)
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts("Invalid timestamp"):
            entrypoint()


def test_freshness_boundary_and_recovery(market):
    feed, oracle = market
    boa.env.time_travel(seconds=MAX_AGE)
    assert oracle.price() == oracle.price_w() == 10**18
    boa.env.time_travel(seconds=1)
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts("Stale price"):
            entrypoint()
    feed.set_round(90_000_000, boa.env.timestamp)
    assert oracle.price() == oracle.price_w() == 9 * 10**17


def test_upstream_failure_propagates(market):
    feed, oracle = market
    feed.set_fail(True)
    for entrypoint in (oracle.price, oracle.price_w):
        with boa.reverts("Feed unavailable"):
            entrypoint()


def test_invalid_deployment_config(market):
    feed, _ = market
    for address, max_age in [(boa.env.generate_address(), MAX_AGE), (feed.address, 0)]:
        with boa.reverts():
            boa.load(SOURCE, address, max_age)
    invalid_feed = FEED_DEPLOYER.deploy(19)
    with boa.reverts():
        boa.load(SOURCE, invalid_feed.address, MAX_AGE)
