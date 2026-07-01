import boa
import pytest

from tests.price_oracles.agg_stable.conftest import (
    MIN_LIQUIDITY,
    OLD_POOL_DEPLOYER,
    WAD,
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

    assert agg.price_pairs(0)[0] == old_pool.address
    assert agg.price_pairs(0)[1] is False
    assert agg.price_pairs(0)[2] is False

    assert agg.price_pairs(1)[0] == inverse_ng_pool.address
    assert agg.price_pairs(1)[1] is True
    assert agg.price_pairs(1)[2] is True

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

    with boa.env.prank(admin):
        for _ in range(19):
            agg.add_price_pair(old_pool_factory().address)

    with boa.reverts(dev="too many pairs"):
        with boa.env.prank(admin):
            agg.add_price_pair(old_pool_factory().address)


def test_add_price_pair_permissions_and_pair_validation(
    agg, old_pool_factory, admin, alice, other_token
):
    valid_pool = old_pool_factory()
    invalid_pool = OLD_POOL_DEPLOYER.deploy(
        admin,
        other_token.address,
        alice,
        WAD,
        MIN_LIQUIDITY,
        WAD,
    )

    with boa.reverts("only admin"):
        with boa.env.prank(alice):
            agg.add_price_pair(valid_pool.address)

    with boa.reverts("not stablecoin pair"):
        with boa.env.prank(admin):
            agg.add_price_pair(invalid_pool.address)


def test_inverse_pair_with_zero_pool_price_reverts(
    agg, old_pool_factory, admin
):
    pool = old_pool_factory(price=0, stable_ix=0)

    with boa.env.prank(admin):
        agg.add_price_pair(pool.address)

    with boa.reverts():
        agg.price()


def test_only_active_sources_are_used(agg, old_pool_factory, admin):
    thin_pool = old_pool_factory(price=8 * WAD // 10, tvl=MIN_LIQUIDITY - 1)
    active_pool = old_pool_factory(price=11 * WAD // 10, tvl=MIN_LIQUIDITY)

    with boa.env.prank(admin):
        agg.add_price_pair(thin_pool.address)
        agg.add_price_pair(active_pool.address)

    assert agg.share_cap() == WAD
    assert agg.price() == 11 * WAD // 10


def test_price_w_checkpoints_tvl_and_caches_same_block(
    agg, old_pool_factory, admin
):
    pool = old_pool_factory(price=WAD, tvl=MIN_LIQUIDITY * 2)
    with boa.env.prank(admin):
        agg.add_price_pair(pool.address)

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


def test_share_cap_admin_flow(agg, old_pool_factory, admin, alice):
    with boa.reverts("only admin"):
        with boa.env.prank(alice):
            agg.set_share_cap(45 * WAD // 100)

    pool_a = old_pool_factory()
    pool_b = old_pool_factory()
    with boa.env.prank(admin):
        agg.add_price_pair(pool_a.address)
        agg.add_price_pair(pool_b.address)
        agg.set_share_cap(55 * WAD // 100)

    assert agg.custom_share_cap() == 55 * WAD // 100
    assert agg.share_cap() == 55 * WAD // 100

    with boa.env.prank(admin):
        agg.set_share_cap(0)
    assert agg.custom_share_cap() == 0
    assert agg.share_cap() == 70 * WAD // 100


def test_remove_price_pair_admin_and_emergency_flow(
    agg, old_pool_factory, admin, emergency_admin, alice
):
    pools = [old_pool_factory(price=(i + 1) * WAD) for i in range(3)]
    with boa.env.prank(admin):
        for pool in pools:
            agg.add_price_pair(pool.address)

    with boa.reverts("only admin"):
        with boa.env.prank(alice):
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

    assert agg.price() == WAD


def test_remove_price_pair_rejects_empty_and_bad_index(
    agg, old_pool_factory, admin
):
    with boa.reverts(dev="no pairs to remove"):
        with boa.env.prank(admin):
            agg.remove_price_pair(0)

    pool = old_pool_factory()
    with boa.env.prank(admin):
        agg.add_price_pair(pool.address)

    with boa.reverts("bad pair index"):
        with boa.env.prank(admin):
            agg.remove_price_pair(1)


def test_admin_can_rotate_roles(agg, admin, emergency_admin, alice):
    with boa.reverts("only admin"):
        with boa.env.prank(alice):
            agg.set_admin(alice)
    with boa.reverts("only admin"):
        with boa.env.prank(alice):
            agg.set_emergency_admin(alice)
    with boa.reverts("only admin"):
        with boa.env.prank(alice):
            agg.set_emergency_remove_count(1)

    with boa.env.prank(admin):
        agg.set_emergency_admin(alice)
        agg.set_emergency_remove_count(2)
        agg.set_admin(emergency_admin)
        logs = _logs(agg, "SetAdmin")
        assert len(logs) == 1
        assert logs[0].admin == emergency_admin

    assert agg.emergency_admin() == alice
    assert agg.emergency_remove_count() == 2
    assert agg.admin() == emergency_admin
