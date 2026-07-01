from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.price_oracles.agg_stable.conftest import WAD


FUZZ_SETTINGS = settings(
    max_examples=35,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@given(
    low_price=st.integers(min_value=50 * WAD // 100, max_value=WAD),
    high_price=st.integers(min_value=WAD, max_value=150 * WAD // 100),
    low_weight=st.integers(min_value=1, max_value=WAD),
    high_weight=st.integers(min_value=1, max_value=WAD),
)
@FUZZ_SETTINGS
def test_exp_penalized_price_stays_in_source_range(
    weighted_price, low_price, high_price, low_weight, high_weight
):
    price = weighted_price.exp_penalized_price(
        [low_price, high_price],
        [low_weight, high_weight],
        WAD,
    )

    assert min(low_price, high_price) <= price <= max(low_price, high_price)


@given(
    price=st.integers(min_value=50 * WAD // 100, max_value=150 * WAD // 100),
    p_ref=st.integers(min_value=50 * WAD // 100, max_value=150 * WAD // 100),
    weights=st.lists(st.integers(min_value=1, max_value=WAD), min_size=1, max_size=5),
)
@FUZZ_SETTINGS
def test_identical_prices_are_invariant(weighted_price, price, p_ref, weights):
    prices = [price] * len(weights)

    assert weighted_price.exp_penalized_price(prices, weights, p_ref) == price


@given(
    delta=st.integers(min_value=10**12, max_value=10**16),
    weight_a=st.integers(min_value=1, max_value=WAD),
    weight_b=st.integers(min_value=1, max_value=WAD),
)
@FUZZ_SETTINGS
def test_symmetric_prices_with_equal_weights_return_reference(
    weighted_price, delta, weight_a, weight_b
):
    weight = min(weight_a, weight_b)

    price = weighted_price.exp_penalized_price(
        [WAD - delta, WAD + delta],
        [weight, weight],
        WAD,
    )

    assert price == WAD


@given(
    outlier_price=st.one_of(
        st.integers(min_value=90 * WAD // 100, max_value=99 * WAD // 100),
        st.integers(min_value=101 * WAD // 100, max_value=110 * WAD // 100),
    ),
)
@FUZZ_SETTINGS
def test_smaller_sigma_moves_outlier_result_toward_reference(
    weighted_price_deployer, outlier_price
):
    narrow = weighted_price_deployer.deploy(10**16)
    wide = weighted_price_deployer.deploy(WAD)

    narrow_price = narrow.exp_penalized_price([WAD, outlier_price], [WAD, WAD], WAD)
    wide_price = wide.exp_penalized_price([WAD, outlier_price], [WAD, WAD], WAD)

    assert min(WAD, outlier_price) <= narrow_price <= max(WAD, outlier_price)
    assert min(WAD, outlier_price) <= wide_price <= max(WAD, outlier_price)
    assert abs(narrow_price - WAD) <= abs(wide_price - WAD)
