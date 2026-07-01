import boa
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.price_oracles.agg_stable.conftest import MIN_LIQUIDITY, WAD


FUZZ_SETTINGS = settings(
    max_examples=35,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@given(
    price=st.integers(min_value=10**16, max_value=10**20),
)
@settings(
    max_examples=30,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_inverse_pair_returns_reciprocal_price(
    agg_deployer,
    stablecoin,
    admin,
    emergency_admin,
    old_pool_factory,
    price,
):
    with boa.env.anchor():
        agg = agg_deployer.deploy(stablecoin.address, 10**16, admin, emergency_admin)
        pool = old_pool_factory(price=price, stable_ix=0)

        with boa.env.prank(admin):
            agg.add_price_pair(pool.address)

        assert agg.price() == 10**36 // price


@given(
    low_price=st.integers(min_value=WAD // 2, max_value=WAD - 1),
    high_price=st.integers(min_value=WAD + 1, max_value=3 * WAD),
    low_tvl=st.integers(min_value=1, max_value=50),
    high_tvl=st.integers(min_value=1, max_value=50),
)
@FUZZ_SETTINGS
def test_aggregate_price_stays_inside_active_source_range(
    agg_deployer,
    stablecoin,
    admin,
    emergency_admin,
    old_pool_factory,
    low_price,
    high_price,
    low_tvl,
    high_tvl,
):
    with boa.env.anchor():
        agg = agg_deployer.deploy(stablecoin.address, 10**16, admin, emergency_admin)
        low_pool = old_pool_factory(
            price=low_price,
            tvl=MIN_LIQUIDITY * low_tvl,
        )
        high_pool = old_pool_factory(
            price=high_price,
            tvl=MIN_LIQUIDITY * high_tvl,
        )

        with boa.env.prank(admin):
            agg.add_price_pair(low_pool.address)
            agg.add_price_pair(high_pool.address)

        price = agg.price()

        assert low_price <= price <= high_price


@given(
    thin_price=st.integers(min_value=WAD // 10, max_value=10 * WAD),
    active_price=st.integers(min_value=WAD // 2, max_value=2 * WAD),
)
@settings(
    max_examples=25,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_sources_below_min_liquidity_do_not_affect_price(
    agg_deployer,
    stablecoin,
    admin,
    emergency_admin,
    old_pool_factory,
    thin_price,
    active_price,
):
    with boa.env.anchor():
        agg = agg_deployer.deploy(stablecoin.address, 10**16, admin, emergency_admin)
        thin_pool = old_pool_factory(price=thin_price, tvl=MIN_LIQUIDITY - 1)
        active_pool = old_pool_factory(price=active_price, tvl=MIN_LIQUIDITY)

        with boa.env.prank(admin):
            agg.add_price_pair(thin_pool.address)
            agg.add_price_pair(active_pool.address)

        assert agg.price() == active_price
