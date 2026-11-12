"""WindowOracle keeps the highs and lows of the last WINDOW seconds at any block time.

It keeps one observation per 12 s: writes in the same 12 s (blocks faster than
Ethereum's) share one, which keeps the highest and the lowest average of them
(and the latest, for when it is the one before the window).
Four observations hold WINDOW = 36 s, so a longer window is rejected.

The pool here reports a set price_oracle with a huge ma_time, so the average the
oracle recovers for each write is exactly the price set before it. TAU = 1 s and
a cap of 100 % per second make hi / lo follow the window's highest / lowest.
"""

import boa
import pytest


@pytest.mark.parametrize("window", [1, 12, 35, 36])
def test_window_accepted(deploy_window_oracle, window):
    assert deploy_window_oracle(window).WINDOW() == window


@pytest.mark.parametrize("window", [37, 48, 120, 3600])
def test_window_too_long(deploy_window_oracle, window):
    with boa.reverts("Window too long"):
        deploy_window_oracle(window)


@pytest.mark.parametrize("block_time", [1, 2, 3, 5])
@pytest.mark.parametrize("step", [2, 1 / 2])
def test_fast_blocks_keep_window_extremes(
    deploy_window_oracle, pool, p0, block_time, step
):
    """One block at `step` x the price: hi (or lo) holds it until the observation is WINDOW old."""
    window = 36
    with boa.env.anchor():
        oracle = deploy_window_oracle(window)
        for _ in range(60 // block_time):
            boa.env.time_travel(seconds=block_time)
            oracle.price_w()

        pool.set_price(int(p0 * step))
        boa.env.time_travel(seconds=block_time)
        oracle.price_w()  # writes the stepped average
        pool.set_price(p0)
        t_written = boa.env.evm.patch.timestamp

        while boa.env.evm.patch.timestamp + block_time < t_written + window:
            boa.env.time_travel(seconds=block_time)
            oracle.price_w()
            hi, lo, _ = oracle.band()
            if step > 1:
                assert hi > p0 * 3 // 2
            else:
                assert lo < p0 * 3 // 4

        # Kept at most one 12 s observation longer
        for _ in range(48 // block_time):
            boa.env.time_travel(seconds=block_time)
            oracle.price_w()
        hi, lo, _ = oracle.band()
        assert hi < p0 * 101 // 100
        assert lo > p0 * 99 // 100


@pytest.mark.parametrize("window", [12, 24, 36])
@pytest.mark.parametrize("block_time", [1, 2, 3])
@pytest.mark.parametrize("step", [2, 1 / 2])
def test_fast_blocks_drop_window_extremes(
    deploy_window_oracle, pool, p0, window, block_time, step
):
    """One block at `step` x the price, at the start of its 12 s: gone less than 12 s after it is WINDOW old."""
    with boa.env.anchor():
        oracle = deploy_window_oracle(window)
        for _ in range(60 // block_time):
            boa.env.time_travel(seconds=block_time)
            oracle.price_w()
        while (boa.env.evm.patch.timestamp + block_time) % 12 != 0:
            boa.env.time_travel(seconds=1)
        oracle.price_w()

        pool.set_price(int(p0 * step))
        boa.env.time_travel(seconds=block_time)
        oracle.price_w()  # writes the stepped average
        pool.set_price(p0)
        t_written = boa.env.evm.patch.timestamp

        # 12 s more, and 6 s for hi / lo to follow
        while boa.env.evm.patch.timestamp < t_written + window + 12 + 6:
            boa.env.time_travel(seconds=block_time)
            oracle.price_w()
        hi, lo, _ = oracle.band()
        assert hi < p0 * 101 // 100
        assert lo > p0 * 99 // 100


@pytest.mark.parametrize("block_time", [1, 2, 3])
@pytest.mark.parametrize("step", [2, 1 / 2])
def test_fast_blocks_keep_window_extremes_mid_observation(
    deploy_window_oracle, pool, p0, block_time, step
):
    """One block at `step` x the price, in the middle of its 12 s: hi (or lo) holds it until it is WINDOW old."""
    window = 36
    with boa.env.anchor():
        oracle = deploy_window_oracle(window)
        for _ in range(60 // block_time):
            boa.env.time_travel(seconds=block_time)
            oracle.price_w()
        while (boa.env.evm.patch.timestamp + block_time) % 12 != 6:
            boa.env.time_travel(seconds=1)
        oracle.price_w()

        pool.set_price(int(p0 * step))
        boa.env.time_travel(seconds=block_time)
        oracle.price_w()  # writes the stepped average
        pool.set_price(p0)
        t_written = boa.env.evm.patch.timestamp

        while boa.env.evm.patch.timestamp + block_time < t_written + window:
            boa.env.time_travel(seconds=block_time)
            oracle.price_w()
            hi, lo, _ = oracle.band()
            if step > 1:
                assert hi > p0 * 3 // 2
            else:
                assert lo < p0 * 3 // 4
