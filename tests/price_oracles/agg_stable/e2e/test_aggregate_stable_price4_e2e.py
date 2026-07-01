import boa

from tests.price_oracles.agg_stable.conftest import MIN_LIQUIDITY, WAD


def _logs(contract, event_name):
    return [log for log in contract.get_logs() if type(log).__name__ == event_name]


def test_admin_recovers_from_bad_dominant_source_with_emergency_removal(
    agg, old_pool_factory, ng_pool_factory, admin, emergency_admin
):
    dominant_bad = old_pool_factory(price=80 * WAD // 100, tvl=MIN_LIQUIDITY * 1_000)
    honest_old = old_pool_factory(price=WAD, tvl=MIN_LIQUIDITY * 2)
    honest_ng = ng_pool_factory(price=WAD, tvl=MIN_LIQUIDITY * 2)

    with boa.env.prank(admin):
        agg.add_price_pair(dominant_bad.address)
        agg.add_price_pair(honest_old.address)
        agg.add_price_pair(honest_ng.address)

    capped_price = agg.price()
    naive_liquidity_price = (
        dominant_bad.price_oracle() * dominant_bad.totalSupply()
        + honest_old.price_oracle() * honest_old.totalSupply()
        + honest_ng.price_oracle(0) * honest_ng.D_oracle()
    ) // (dominant_bad.totalSupply() + honest_old.totalSupply() + honest_ng.D_oracle())

    assert capped_price > naive_liquidity_price
    assert capped_price > 90 * WAD // 100

    with boa.env.prank(admin):
        agg.set_emergency_remove_count(1)

    with boa.env.prank(emergency_admin):
        agg.remove_price_pair(0)

    assert agg.emergency_remove_count() == 0
    assert agg.price() == WAD


def test_oracle_handles_pool_lifecycle_and_price_updates(
    agg, old_pool_factory, ng_pool_factory, admin
):
    old_pool = old_pool_factory(price=WAD, tvl=MIN_LIQUIDITY * 2)
    inverse_pool = ng_pool_factory(price=2 * WAD, tvl=MIN_LIQUIDITY * 2, stable_ix=0)

    with boa.env.prank(admin):
        agg.add_price_pair(old_pool.address)
        agg.add_price_pair(inverse_pool.address)

    assert agg.price() < WAD

    with boa.env.prank(admin):
        inverse_pool.set_price(WAD)

    assert agg.price() == WAD
    assert agg.price_w() == WAD

    with boa.env.prank(admin):
        old_pool.set_price(105 * WAD // 100)
        inverse_pool.set_tvl(MIN_LIQUIDITY - 1)

    boa.env.time_travel(agg.TVL_MA_TIME() * 2)

    assert agg.price_w() == 105 * WAD // 100

    with boa.env.prank(admin):
        agg.remove_price_pair(0)

    assert agg.price() == WAD


def test_admin_configures_oracle_and_events_match_state(
    agg, old_pool_factory, ng_pool_factory, admin, emergency_admin, new_emergency_admin
):
    old_pool = old_pool_factory(price=99 * WAD // 100, tvl=MIN_LIQUIDITY * 3)
    ng_pool = ng_pool_factory(price=101 * WAD // 100, tvl=MIN_LIQUIDITY * 3)

    with boa.env.prank(admin):
        agg.add_price_pair(old_pool.address)
        add_logs = _logs(agg, "AddPricePair")
        assert len(add_logs) == 1
        assert add_logs[0].pool == old_pool.address

        agg.add_price_pair(ng_pool.address)
        add_logs = _logs(agg, "AddPricePair")
        assert len(add_logs) == 1
        assert add_logs[0].pool == ng_pool.address

        agg.set_share_cap(45 * WAD // 100)
        share_cap_logs = _logs(agg, "SetShareCap")
        assert len(share_cap_logs) == 1
        assert share_cap_logs[0].share_cap == 45 * WAD // 100

        agg.set_emergency_admin(new_emergency_admin)
        emergency_admin_logs = _logs(agg, "SetEmergencyAdmin")
        assert len(emergency_admin_logs) == 1
        assert emergency_admin_logs[0].emergency_admin == new_emergency_admin

        agg.set_emergency_remove_count(1)
        count_logs = _logs(agg, "SetEmergencyRemoveCount")
        assert len(count_logs) == 1
        assert count_logs[0].emergency_remove_count == 1

    assert agg.custom_share_cap() == 45 * WAD // 100
    assert agg.share_cap() == 45 * WAD // 100
    assert agg.emergency_admin() == new_emergency_admin
    assert agg.emergency_remove_count() == 1
    assert 99 * WAD // 100 <= agg.price() <= 101 * WAD // 100

    with boa.env.prank(new_emergency_admin):
        agg.remove_price_pair(1)
        remove_logs = _logs(agg, "RemovePricePair")
        assert len(remove_logs) == 1
        assert remove_logs[0].n == 1

    assert agg.emergency_remove_count() == 0
    assert agg.price_pairs(0)[0] == old_pool.address
    assert agg.price() == 99 * WAD // 100
