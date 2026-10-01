import math

import boa
import pytest

from tests.integration.lp_oracle_stable_swap_ng_pump.conftest import DUMMY_POOL_DEPLOYER
from tests.utils.deployers import LP_ORACLE_STABLESWAP_NG_DEPLOYER


WAD = 10**18
EMA_TIME = 866


@pytest.mark.parametrize("cadence", [12, 60, 600, 3600, 86400])
def test_chained_ema_cadence(adapter, feed, cadence):
    pool = DUMMY_POOL_DEPLOYER.deploy(20_000, WAD, WAD)
    lp = LP_ORACLE_STABLESWAP_NG_DEPLOYER.deploy(pool, 0, EMA_TIME)
    agg = boa.loads("""
# pragma version 0.4.3
@external
@view
def price() -> uint256:
    return 997 * 10**15
@external
def price_w() -> uint256:
    return 997 * 10**15
""")
    chain = boa.load(
        "curve_stablecoin/price_oracles/v2/ChainOracle.vy", [lp, adapter, agg]
    )
    initial = lp.price()
    feed.set_value(99 * WAD // 100)
    expected = (lp.price() * adapter.price() // WAD) * agg.price() // WAD
    assert chain.price() == chain.price_w() == expected

    pool.set_virtual_price(11 * WAD // 10)
    # Reads after idle do not enqueue the new virtual price.
    boa.env.time_travel(seconds=cadence)
    assert lp.price() == initial
    assert chain.price() == chain.price_w() == expected
    assert chain.price_w() == expected

    boa.env.time_travel(seconds=cadence)
    expected_vp = WAD + (WAD // 10) * (1 - math.exp(-cadence / EMA_TIME))
    assert abs(lp.price() - initial * expected_vp / WAD) < 1000
    assert chain.price() == chain.price_w()
    # A newly deployed oracle seeds from spot, unlike the carried EMA.
    fresh = LP_ORACLE_STABLESWAP_NG_DEPLOYER.deploy(pool, 0, EMA_TIME)
    assert fresh.price() == initial * 11 // 10
    assert fresh.price() >= lp.price()

    pool.set_virtual_price(9 * WAD // 10)
    assert lp.price() == lp.price_w() == initial * 9 // 10
    feed.set_value(WAD)
    assert chain.price() == chain.price_w() == lp.price() * agg.price() // WAD


def test_chain_propagates_failed_feed(adapter, feed):
    chain = boa.load("curve_stablecoin/price_oracles/v2/ChainOracle.vy", [adapter])
    feed.set_fail(True)
    with boa.reverts("feed unavailable"):
        chain.price()
    with boa.reverts("feed unavailable"):
        chain.price_w()
