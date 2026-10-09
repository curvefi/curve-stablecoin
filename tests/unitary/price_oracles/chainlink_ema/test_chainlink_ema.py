import boa

from tests.unitary.price_oracles.chainlink_ema.conftest import (
    INTERVAL,
    MAX_LOOKBACK,
    PRECISION_MUL,
    next_ema,
    observation,
    sample,
)


PRICE = 3000 * 10**8


def now():
    return boa.env.evm.patch.timestamp


def reseed(rounds, obs):
    samples = []
    for _ in range(MAX_LOOKBACK):
        samples.append(sample(rounds, obs))
        obs -= INTERVAL
    ema = samples[-1]
    for price in reversed(samples[:-1]):
        ema = next_ema(price, ema)
    return ema


def test_constant_price(feed, deploy_oracle):
    feed.add_rounds(1, PRICE, now() - 7200, 600, 12)
    oracle = deploy_oracle()
    assert oracle.price() == PRICE * PRECISION_MUL

    boa.env.time_travel(seconds=INTERVAL * 7)
    assert oracle.price() == PRICE * PRECISION_MUL
    assert oracle.price_w() == PRICE * PRECISION_MUL


def test_ema_matches_reference(feed, deploy_oracle):
    feed.add_rounds(1, PRICE, now() - 7200, 600, 12)
    rounds = [(PRICE * PRECISION_MUL, now() - 7200 + i * 600) for i in range(12)]
    oracle = deploy_oracle()
    ema = PRICE * PRECISION_MUL
    stored = observation(now())

    # gaps under MAX_LOOKBACK * INTERVAL take the incremental path, 1500 forces a reseed
    gaps = [7, 31, 45, 90, 300, 13, 600, 1500, 61, 29, 1199, 30, 1]
    for i, gap in enumerate(gaps):
        answer = PRICE + (i % 3 - 1) * (i + 1) * 10**9
        feed.add_rounds(1, answer, now(), 1, 1)
        rounds.append((answer * PRECISION_MUL, now()))
        boa.env.time_travel(seconds=gap)

        current = observation(now())
        if stored + MAX_LOOKBACK * INTERVAL > current:
            while stored < current:
                stored += INTERVAL
                ema = next_ema(sample(rounds, stored), ema)
        else:
            ema = reseed(rounds, current)
            stored = current

        assert oracle.price() == ema
        assert oracle.price_w() == ema
        assert oracle.storedPrice() == ema


def test_phase_switch_reseeds_instead_of_walking_new_aggregator(feed, deploy_oracle):
    feed.add_rounds(1, PRICE, now() - 7200, 600, 12)
    # the next aggregator posts in parallel for days before the proxy switches to it
    for i in range(6):
        feed.add_rounds(2, PRICE + 10**10, now() - 360_000 + i * 60_000, 60, 1000)
    oracle = deploy_oracle()
    oracle.price_w()

    boa.env.time_travel(seconds=600)
    feed.set_phase(2)
    feed.add_rounds(2, PRICE + 2 * 10**10, now(), 1, 1)
    boa.env.time_travel(seconds=INTERVAL)

    expected = deploy_oracle().price()
    price = oracle.price()
    price_gas = oracle._computation.get_gas_used()
    price_w = oracle.price_w()
    price_w_gas = oracle._computation.get_gas_used()
    # walking all 6000 pre-switch rounds costs tens of millions of gas
    assert price_gas < 1_000_000
    assert price_w_gas < 1_000_000
    assert price == price_w == expected
    assert oracle.storedResponse()[0] == (2 << 64) | 6001


def test_phase_switch_without_new_aggregator_history(feed, deploy_oracle):
    feed.add_rounds(1, PRICE, now() - 7200, 600, 12)
    oracle = deploy_oracle()
    oracle.price_w()

    boa.env.time_travel(seconds=600)
    feed.set_phase(2)
    feed.add_rounds(2, PRICE + 10**10, now(), 1, 1)

    # with no rounds before the current observation the reseed falls back to the latest answer
    assert oracle.price_w() == (PRICE + 10**10) * PRECISION_MUL
