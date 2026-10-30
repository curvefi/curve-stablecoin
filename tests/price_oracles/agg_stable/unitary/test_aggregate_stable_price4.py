import math

import boa
import pytest

from tests.price_oracles.agg_stable.conftest import (
    BROKEN_NG_POOL_DEPLOYER,
    BROKEN_OLD_POOL_DEPLOYER,
    EMPTY_PROBE_POOL_DEPLOYER,
    MIN_LIQUIDITY,
    OLD_POOL_DEPLOYER,
    WAD,
    warm_up,
)
from tests.utils.constants import ZERO_ADDRESS


def _logs(contract, event_name):
    return [log for log in contract.get_logs() if type(log).__name__ == event_name]


def test_constructor_initializes_public_state(
    agg_deployer, stablecoin, admin, emergency_admin
):
    agg = agg_deployer.deploy(stablecoin.address, 10**16, admin, emergency_admin)

    assert agg.stablecoin() == stablecoin.address
    assert agg.sigma() == 10**16
    assert agg.admin() == admin
    assert agg.emergency_admin() == emergency_admin
    assert agg.price() == WAD
    assert agg.price_w() == WAD


def test_constructor_rejects_bad_parameters(
    agg_deployer, stablecoin, admin, emergency_admin
):
    with boa.reverts("zero stablecoin"):
        agg_deployer.deploy(ZERO_ADDRESS, 10**16, admin, emergency_admin)
    with boa.reverts("zero admin"):
        agg_deployer.deploy(stablecoin.address, 10**16, ZERO_ADDRESS, emergency_admin)
    with boa.reverts("bad sigma value"):
        agg_deployer.deploy(stablecoin.address, 10**9 - 1, admin, emergency_admin)
    with boa.reverts("bad sigma value"):
        agg_deployer.deploy(stablecoin.address, WAD + 1, admin, emergency_admin)


def test_add_price_pair_detects_old_ng_and_inverse(
    agg, old_pool_factory, ng_pool_factory, admin
):
    old_pool = old_pool_factory(price=2 * WAD, stable_ix=1)
    inverse_ng_pool = ng_pool_factory(price=2 * WAD, stable_ix=0)

    with boa.env.prank(admin):
        agg.add_price_pair(old_pool.address)
        agg.add_price_pair(inverse_ng_pool.address)
    warm_up(agg)

    assert agg.price_pairs(0)[0] == old_pool.address
    assert agg.price_pairs(0)[1] is False
    assert agg.price_pairs(0)[2] is False

    assert agg.price_pairs(1)[0] == inverse_ng_pool.address
    assert agg.price_pairs(1)[1] is True
    assert agg.price_pairs(1)[2] is True

    assert agg.n_price_pairs() == 2
    assert agg.ema_tvl() == [MIN_LIQUIDITY * 2, MIN_LIQUIDITY * 2]
    assert agg.price() == pytest.approx(5 * WAD // 4, rel=1e-12)


def test_add_price_pair_emits_event_and_rejects_too_many_sources(
    agg, old_pool_factory, admin
):
    with boa.env.prank(admin):
        first_pool = old_pool_factory()
        agg.add_price_pair(first_pool.address)

    logs = _logs(agg, "AddPricePair")
    assert len(logs) == 1
    assert logs[0].n == 0
    assert logs[0].pool == first_pool.address
    assert logs[0].is_inverse is False
    assert logs[0].is_ng is False

    with boa.env.prank(admin):
        for _ in range(19):
            agg.add_price_pair(old_pool_factory().address)

    with boa.reverts(dev="too many pairs"):
        with boa.env.prank(admin):
            agg.add_price_pair(old_pool_factory().address)


def test_add_price_pair_permissions_and_pair_validation(
    agg, old_pool_factory, admin, new_emergency_admin, other_token
):
    valid_pool = old_pool_factory()
    invalid_pool = OLD_POOL_DEPLOYER.deploy(
        admin,
        other_token.address,
        new_emergency_admin,
        WAD,
        MIN_LIQUIDITY,
        WAD,
    )

    with boa.reverts("only admin"):
        with boa.env.prank(new_emergency_admin):
            agg.add_price_pair(valid_pool.address)

    with boa.reverts("not stablecoin pair"):
        with boa.env.prank(admin):
            agg.add_price_pair(invalid_pool.address)


def test_add_price_pair_rejects_zero_pool_price(agg, old_pool_factory, admin):
    direct_pool = old_pool_factory(price=0, stable_ix=1)
    inverse_pool = old_pool_factory(price=0, stable_ix=0)

    with boa.reverts("bad price"):
        with boa.env.prank(admin):
            agg.add_price_pair(direct_pool.address)

    with boa.reverts():
        with boa.env.prank(admin):
            agg.add_price_pair(inverse_pool.address)

    assert agg.n_price_pairs() == 0


def test_add_price_pair_rejects_incompatible_pools(agg, admin, stablecoin, redeemable):
    coins = (redeemable.address, stablecoin.address)
    broken_ng = BROKEN_NG_POOL_DEPLOYER.deploy(*coins)
    broken_old = BROKEN_OLD_POOL_DEPLOYER.deploy(*coins)
    empty_probe = EMPTY_PROBE_POOL_DEPLOYER.deploy(*coins)

    for pool in (broken_ng, broken_old, empty_probe):
        with boa.reverts():
            with boa.env.prank(admin):
                agg.add_price_pair(pool.address)

    assert agg.n_price_pairs() == 0


def test_add_price_pair_rejects_duplicate_pool(agg, old_pool_factory, admin):
    pool = old_pool_factory()
    other_pool = old_pool_factory()

    with boa.env.prank(admin):
        agg.add_price_pair(pool.address)
        agg.add_price_pair(other_pool.address)

    with boa.reverts("pool already added"):
        with boa.env.prank(admin):
            agg.add_price_pair(pool.address)

    assert agg.n_price_pairs() == 2


def test_empty_pools_can_be_registered_and_stay_inactive(
    agg, old_pool_factory, ng_pool_factory, admin
):
    empty_old = old_pool_factory(price=WAD, tvl=0)
    empty_ng = ng_pool_factory(price=WAD, tvl=0)
    active_pool = old_pool_factory(price=11 * WAD // 10)

    with boa.env.prank(admin):
        agg.add_price_pair(empty_old.address)
        agg.add_price_pair(empty_ng.address)
        agg.add_price_pair(active_pool.address)
    warm_up(agg)

    assert agg.last_tvl(0) == 0
    assert agg.last_tvl(1) == 0
    assert agg.ema_tvl() == [0, 0, MIN_LIQUIDITY * 2]
    assert agg.price() == 11 * WAD // 10

    boa.env.time_travel(agg.TVL_MA_TIME())
    assert agg.ema_tvl() == [0, 0, MIN_LIQUIDITY * 2]
    assert agg.price_w() == 11 * WAD // 10


def test_zero_supply_legacy_pool_does_not_block_price(agg, old_pool_factory, admin):
    drained_pool = old_pool_factory(price=WAD)
    active_pool = old_pool_factory(price=12 * WAD // 10)

    with boa.env.prank(admin):
        agg.add_price_pair(drained_pool.address)
        agg.add_price_pair(active_pool.address)
    warm_up(agg)
    with boa.env.prank(admin):
        drained_pool.set_tvl(0, WAD)

    with boa.reverts(dev="zero supply"):
        drained_pool.get_virtual_price()

    boa.env.time_travel(agg.TVL_MA_TIME())

    # The drained source decays towards zero instead of reverting every read.
    assert agg.ema_tvl()[0] < MIN_LIQUIDITY * 2
    assert agg.price() == 12 * WAD // 10
    assert agg.price_w() == 12 * WAD // 10
    assert agg.share_cap() == WAD

    boa.env.time_travel(agg.TVL_MA_TIME() * 20)
    agg.price_w()
    assert agg.last_tvl(0) < WAD  # exp(-20) dust of the initial TVL


def test_legacy_source_phases_in_from_zero(agg, old_pool_factory, admin):
    supply = MIN_LIQUIDITY * 2
    virtual_price = 11 * WAD // 10
    tvl = supply * virtual_price // WAD
    pool = old_pool_factory(
        price=12 * WAD // 10, tvl=supply, virtual_price=virtual_price
    )

    with boa.env.prank(admin):
        agg.add_price_pair(pool.address)

    # Liquidity present at registration does not seed the source's weight.
    assert agg.last_tvl(0) == 0
    assert agg.ema_tvl() == [0]
    assert agg.price() == WAD

    # The EMA observation is totalSupply * virtual_price and phases in over time.
    boa.env.time_travel(agg.TVL_MA_TIME())
    assert agg.ema_tvl()[0] == pytest.approx(tvl * (1 - math.exp(-1)), rel=1e-9)
    assert agg.price() == 12 * WAD // 10

    warm_up(agg)
    assert agg.last_tvl(0) == tvl


def test_only_active_sources_are_used(agg, old_pool_factory, admin):
    thin_pool = old_pool_factory(price=8 * WAD // 10, tvl=MIN_LIQUIDITY - 1)
    active_pool = old_pool_factory(price=11 * WAD // 10, tvl=MIN_LIQUIDITY)

    with boa.env.prank(admin):
        agg.add_price_pair(thin_pool.address)
        agg.add_price_pair(active_pool.address)
    warm_up(agg)

    assert agg.share_cap() == WAD
    assert agg.price() == 11 * WAD // 10


def test_price_w_checkpoints_tvl_and_caches_same_block(agg, old_pool_factory, admin):
    pool = old_pool_factory(price=WAD, tvl=MIN_LIQUIDITY * 2)
    with boa.env.prank(admin):
        agg.add_price_pair(pool.address)
    warm_up(agg)

    assert agg.price_w() == WAD

    with boa.env.prank(admin):
        pool.set_price(12 * WAD // 10)
        pool.set_tvl(MIN_LIQUIDITY * 4, WAD)

    assert agg.price() == 12 * WAD // 10
    assert agg.price_w() == WAD

    boa.env.time_travel(agg.TVL_MA_TIME())
    assert agg.price_w() == 12 * WAD // 10
    assert agg.last_tvl(0) > MIN_LIQUIDITY * 2


def test_ng_tvl_is_not_ema_smoothed(agg, ng_pool_factory, admin):
    pool = ng_pool_factory(price=WAD, tvl=MIN_LIQUIDITY * 2)
    with boa.env.prank(admin):
        agg.add_price_pair(pool.address)
        pool.set_tvl(MIN_LIQUIDITY * 4)

    assert agg.ema_tvl() == [MIN_LIQUIDITY * 4]


def test_share_cap_admin_flow(agg, old_pool_factory, admin, new_emergency_admin):
    with boa.reverts("only admin"):
        with boa.env.prank(new_emergency_admin):
            agg.set_share_cap(45 * WAD // 100)

    pool_a = old_pool_factory()
    pool_b = old_pool_factory()
    with boa.env.prank(admin):
        agg.add_price_pair(pool_a.address)
        agg.add_price_pair(pool_b.address)
    warm_up(agg)
    with boa.env.prank(admin):
        agg.set_share_cap(55 * WAD // 100)

    assert agg.custom_share_cap() == 55 * WAD // 100
    assert agg.share_cap() == 55 * WAD // 100

    with boa.env.prank(admin):
        agg.set_share_cap(0)
    assert agg.custom_share_cap() == 0
    assert agg.share_cap() == 70 * WAD // 100


def test_remove_price_pair_admin_and_emergency_flow(
    agg, old_pool_factory, admin, emergency_admin, new_emergency_admin
):
    pools = [old_pool_factory(price=(i + 1) * WAD) for i in range(3)]
    with boa.env.prank(admin):
        for pool in pools:
            agg.add_price_pair(pool.address)

    with boa.reverts("only admin"):
        with boa.env.prank(new_emergency_admin):
            agg.remove_price_pair(0)

    with boa.reverts(dev="no emergency removals"):
        with boa.env.prank(emergency_admin):
            agg.remove_price_pair(0)

    with boa.env.prank(admin):
        agg.set_emergency_remove_count(1)

    with boa.env.prank(emergency_admin):
        agg.remove_price_pair(1)

    assert agg.emergency_remove_count() == 0
    assert agg.price_pairs(1)[0] == pools[2].address

    with boa.env.prank(admin):
        agg.remove_price_pair(1)
        agg.remove_price_pair(0)

    assert agg.n_price_pairs() == 0
    assert agg.price() == WAD


def test_remove_price_pair_clears_tail_slot(agg, old_pool_factory, admin):
    pools = [old_pool_factory(price=(i + 1) * WAD) for i in range(3)]
    with boa.env.prank(admin):
        for pool in pools:
            agg.add_price_pair(pool.address)
    warm_up(agg)

    with boa.env.prank(admin):
        agg.remove_price_pair(0)

    logs = _logs(agg, "RemovePricePair")
    assert len(logs) == 1
    assert logs[0].n == 0
    assert logs[0].pool == pools[0].address
    move_logs = _logs(agg, "MovePricePair")
    assert len(move_logs) == 1
    assert (move_logs[0].n_from, move_logs[0].n_to) == (2, 0)

    assert agg.n_price_pairs() == 2
    assert agg.price_pairs(0)[0] == pools[2].address
    assert agg.price_pairs(1)[0] == pools[1].address
    assert agg.price_pairs(2) == (ZERO_ADDRESS, False, False)
    assert agg.last_tvl(2) == 0
    assert agg.ema_tvl() == [MIN_LIQUIDITY * 2, MIN_LIQUIDITY * 2]

    # Removed pool can be registered again.
    with boa.env.prank(admin):
        agg.add_price_pair(pools[0].address)
    assert agg.price_pairs(2)[0] == pools[0].address


def test_remove_price_pair_rejects_empty_and_bad_index(agg, old_pool_factory, admin):
    with boa.reverts(dev="no pairs to remove"):
        with boa.env.prank(admin):
            agg.remove_price_pair(0)

    pool = old_pool_factory()
    with boa.env.prank(admin):
        agg.add_price_pair(pool.address)

    with boa.reverts("bad pair index"):
        with boa.env.prank(admin):
            agg.remove_price_pair(1)


def test_admin_can_rotate_roles(agg, admin, emergency_admin, new_emergency_admin):
    with boa.reverts("only admin"):
        with boa.env.prank(new_emergency_admin):
            agg.set_admin(new_emergency_admin)
    with boa.reverts("only admin"):
        with boa.env.prank(new_emergency_admin):
            agg.set_emergency_admin(new_emergency_admin)
    with boa.reverts("only admin"):
        with boa.env.prank(new_emergency_admin):
            agg.set_emergency_remove_count(1)

    with boa.env.prank(admin):
        agg.set_emergency_admin(new_emergency_admin)
        agg.set_emergency_remove_count(2)
        agg.set_admin(emergency_admin)
        logs = _logs(agg, "SetAdmin")
        assert len(logs) == 1
        assert logs[0].admin == emergency_admin

    assert agg.emergency_admin() == new_emergency_admin
    assert agg.emergency_remove_count() == 2
    assert agg.admin() == emergency_admin
