import boa
import pytest


def test_price_aggregator(stableswap_a, stableswap_b, stablecoin_a, agg, admin):
    amount = 300_000 * 10**6
    dt = 86400

    assert agg.price() == pytest.approx(10**18, rel=1e-6)
    assert agg.price_pairs(0)[0].lower() == stableswap_a.address.lower()
    assert agg.price_pairs(1)[0].lower() == stableswap_b.address.lower()

    # Make ema_tvl and D_oracle (between old and -ng pools) equal
    for i in range(2):
        agg.eval(f"self.last_tvl[{i}] = self.price_pairs[{i}].pool.totalSupply()")
    with boa.env.anchor():
        with boa.env.prank(admin):
            boa.deal(stablecoin_a, admin, amount)
            stableswap_a.exchange(0, 1, amount, 0)
            p = stableswap_a.get_p()
            assert p > 10**18 * 1.01

            boa.env.time_travel(dt)

            p_o = stableswap_a.price_oracle()
            assert p_o == pytest.approx(p, rel=1e-4)

            # Two coins => agg price is average of the two
            assert agg.price() == pytest.approx((p_o + 10**18) / 2, rel=1e-3)
