from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.price_oracles.agg_stable.conftest import WAD


FUZZ_SETTINGS = settings(
    max_examples=40,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@given(
    liquidities=st.lists(
        st.integers(min_value=1, max_value=10**12),
        min_size=1,
        max_size=8,
    )
)
@FUZZ_SETTINGS
def test_capped_weights_sum_range_and_cap(capped_share, liquidities):
    weights = capped_share.capped_weights(liquidities)
    cap = capped_share.share_cap(len(liquidities))

    assert len(weights) == len(liquidities)
    assert all(0 <= weight <= cap for weight in weights)
    assert sum(weights) <= WAD
    assert sum(weights) >= WAD - len(weights)


@given(
    n_sources=st.integers(min_value=1, max_value=8),
    liquidity=st.integers(min_value=1, max_value=10**12),
)
@FUZZ_SETTINGS
def test_equal_liquidity_sources_get_equal_weights(capped_share, n_sources, liquidity):
    weights = capped_share.capped_weights([liquidity] * n_sources)

    assert len(set(weights)) == 1
    assert weights[0] <= capped_share.share_cap(n_sources)


@given(
    custom_cap=st.integers(min_value=WAD // 100, max_value=90 * WAD // 100),
    small_liquidity=st.integers(min_value=1, max_value=10**12),
    dominance=st.integers(min_value=100, max_value=10_000),
)
@FUZZ_SETTINGS
def test_dominant_source_is_limited_by_custom_cap(
    capped_share, custom_cap, small_liquidity, dominance
):
    capped_share.set_share_cap(custom_cap)

    dominant_liquidity = small_liquidity * dominance
    weights = capped_share.capped_weights(
        [dominant_liquidity, small_liquidity, small_liquidity]
    )

    assert weights[0] <= custom_cap
    assert weights[1] == weights[2]
    assert weights[0] < dominant_liquidity * WAD // (
        dominant_liquidity + 2 * small_liquidity
    )


@given(
    a=st.integers(min_value=1, max_value=10**12),
    b=st.integers(min_value=1, max_value=10**12),
    c=st.integers(min_value=1, max_value=10**12),
)
@FUZZ_SETTINGS
def test_reordering_liquidity_reorders_weights(capped_share, a, b, c):
    weights = capped_share.capped_weights([a, b, c])
    reversed_weights = capped_share.capped_weights([c, b, a])

    assert weights == list(reversed(reversed_weights))
