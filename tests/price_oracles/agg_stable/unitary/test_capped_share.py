import boa
import pytest

from tests.price_oracles.agg_stable.conftest import WAD


def _logs(contract, event_name):
    return [log for log in contract.get_logs() if type(log).__name__ == event_name]


def test_default_cap_schedule(capped_share):
    assert capped_share.default_cap(0) == WAD
    assert capped_share.default_cap(1) == WAD
    assert capped_share.default_cap(2) == 70 * WAD // 100
    assert capped_share.default_cap(3) == 45 * WAD // 100
    assert capped_share.default_cap(5) == 45 * WAD // 100
    assert capped_share.default_cap(6) == 24 * WAD // 100
    assert capped_share.default_cap(64) == 24 * WAD // 100


def test_custom_cap_bounds_event_and_reset(capped_share):
    with boa.reverts("share cap too low"):
        capped_share.set_share_cap(WAD // 100 - 1)
    with boa.reverts("share cap too high"):
        capped_share.set_share_cap(WAD + 1)

    capped_share.set_share_cap(55 * WAD // 100)
    logs = _logs(capped_share, "SetShareCap")
    assert len(logs) == 1
    assert logs[0].share_cap == 55 * WAD // 100
    assert capped_share.custom_share_cap() == 55 * WAD // 100
    assert capped_share.share_cap(3) == 55 * WAD // 100

    capped_share.set_share_cap(0)
    assert capped_share.custom_share_cap() == 0
    assert capped_share.share_cap(3) == 45 * WAD // 100


def test_capped_weights_equal_liquidity_use_equal_shares(capped_share):
    weights = capped_share.capped_weights([10, 10, 10])

    assert len(weights) == 3
    assert weights == [WAD // 3, WAD // 3, WAD // 3]


def test_capped_weights_closed_form_with_dominant_source(capped_share):
    capped_share.set_share_cap(WAD // 2)

    weights = capped_share.capped_weights([9, 1])

    assert weights == [WAD // 2, WAD // 2]


def test_capped_weights_preserve_order_for_ordered_liquidity(capped_share):
    capped_share.set_share_cap(60 * WAD // 100)

    weights = capped_share.capped_weights([1, 2, 4])

    assert weights[0] < weights[1] < weights[2]
    assert max(weights) <= 60 * WAD // 100
    assert sum(weights) <= WAD
    assert sum(weights) >= WAD - len(weights)


def test_capped_weights_symmetric_sources_match(capped_share):
    capped_share.set_share_cap(45 * WAD // 100)

    weights = capped_share.capped_weights([100, 1, 1])

    assert weights[0] == 45 * WAD // 100
    assert weights[1] == weights[2]
    assert sum(weights) <= WAD


def test_capped_weights_empty_input_returns_empty(capped_share):
    assert capped_share.capped_weights([]) == []


def test_capped_weights_zero_liquidity_returns_zero_weights(capped_share):
    assert capped_share.capped_weights([0, 0]) == [0, 0]


@pytest.mark.parametrize("n_sources", [1, 2, 3, 6])
def test_capped_weights_never_exceed_effective_cap(capped_share, n_sources):
    weights = capped_share.capped_weights(list(range(1, n_sources + 1)))
    cap = capped_share.share_cap(n_sources)

    assert all(0 <= weight <= cap for weight in weights)
    assert sum(weights) <= WAD
