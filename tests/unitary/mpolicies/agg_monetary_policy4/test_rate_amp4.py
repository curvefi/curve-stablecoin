"""Tests for AggMonetaryPolicy4 rate calculation."""

import boa

from tests.utils.deployers import MOCK_FACTORY_DEPLOYER, MOCK_MARKET_DEPLOYER
from tests.utils.constants import ZERO_ADDRESS

MAX_RATE = 43959106799


def _seed_discounted_rate_state(
    admin,
    mock_factory,
    peg_keepers,
    mp,
    *,
    ceiling,
    debt,
    pk_debt,
):
    with boa.env.prank(admin):
        market = MOCK_MARKET_DEPLOYER.deploy()
        mock_factory.add_market(market.address, ceiling)
        mock_factory.set_debt(market.address, debt)
        peg_keepers[0].set_debt(pk_debt)
        mp.rate_write(market.address)

        rate_before_zero = mp.rate(market.address)
        peg_keepers[0].set_debt(0)
        rate_after_zero = mp.rate(market.address)

    return {
        "market": market,
        "mp": mp,
        "rate_before_zero": rate_before_zero,
        "rate_after_zero": rate_after_zero,
    }


def test_rate_keeps_ema_discount_active(
    admin,
    default_ema_time,
    mock_factory,
    peg_keepers,
    mp,
):
    """Zeroing current PegKeeper debt should not bypass the existing EMA discount."""
    state = _seed_discounted_rate_state(
        admin,
        mock_factory,
        peg_keepers,
        mp,
        ceiling=10**30,
        debt=10**24,
        pk_debt=5 * 10**22,
    )

    assert state["rate_after_zero"] == state["rate_before_zero"]

    boa.env.time_travel(seconds=default_ema_time)

    with boa.env.prank(admin):
        mp.rate_write(state["market"].address)

    assert mp.rate(state["market"].address) > state["rate_after_zero"]


def test_zero_ceiling_pushes_rate_to_max(
    admin,
    mock_factory,
    peg_keepers,
    mp,
):
    """A zero controller ceiling should force the rate multiplier to the cap."""
    state = _seed_discounted_rate_state(
        admin,
        mock_factory,
        peg_keepers,
        mp,
        ceiling=0,
        debt=8 * 10**23,
        pk_debt=5 * 10**22,
    )

    assert state["rate_before_zero"] == MAX_RATE
    assert state["rate_after_zero"] == MAX_RATE


def test_rate_before_cache_refresh(
    admin,
    price_oracle,
    peg_keepers,
    deployer,
    default_rate,
    default_sigma,
    default_target_debt_fraction,
    default_extra_const,
    default_ema_time,
):
    """rate() includes controllers added after the last rate_write() cache refresh."""
    factory = MOCK_FACTORY_DEPLOYER.deploy()
    pk_array = [pk.address for pk in peg_keepers] + [ZERO_ADDRESS] * (
        5 - len(peg_keepers)
    )

    with boa.env.prank(admin):
        mp = deployer.deploy(
            admin,
            price_oracle.address,
            factory.address,
            pk_array,
            default_rate,
            default_sigma,
            default_target_debt_fraction,
            default_extra_const,
            default_ema_time,
        )
        market = MOCK_MARKET_DEPLOYER.deploy()
        factory.add_market(market.address, 10**24)
        factory.set_debt(market.address, 9 * 10**23)

        view_rate = mp.rate(market.address)
        write_rate = mp.rate_write(market.address)

    assert view_rate == write_rate
