import boa
import pytest

from tests.unitary.price_oracles.reusd_crvusd_adapter.conftest import (
    FEED_ADDRESS,
    WAD,
)


def test_feed_address(adapter):
    assert adapter.REUSD_FEED() == FEED_ADDRESS


@pytest.mark.parametrize(
    "feed_price, expected",
    [
        (0, 0),
        (WAD // 2, WAD // 2),
        (99 * WAD // 100, 99 * WAD // 100),
        (WAD - 1, WAD - 1),
        (WAD, WAD),
        (WAD + 1, WAD),
        (2**256 - 1, WAD),
    ],
)
def test_cap_and_entrypoints(adapter, feed, feed_price, expected):
    feed.set_value(feed_price)
    assert adapter.price() == expected
    assert adapter.price_w() == expected


def test_no_adapter_smoothing(adapter, feed):
    feed.set_value(WAD)
    adapter.price_w()
    feed.set_value(99 * WAD // 100)
    assert adapter.price() == 99 * WAD // 100
    assert adapter.price_w() == 99 * WAD // 100
    feed.set_value(WAD)
    assert adapter.price() == WAD
    boa.env.time_travel(seconds=866)
    assert adapter.price_w() == WAD


@pytest.mark.parametrize("entrypoint", ["price", "price_w"])
def test_upstream_failure_propagates(adapter, feed, entrypoint):
    feed.set_fail(True)
    with boa.reverts("feed unavailable"):
        getattr(adapter, entrypoint)()
