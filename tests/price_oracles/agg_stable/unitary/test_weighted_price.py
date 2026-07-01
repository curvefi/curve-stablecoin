import boa
import pytest

from tests.price_oracles.agg_stable.conftest import WAD


def test_constructor_validates_sigma(weighted_price_deployer):
    with boa.reverts("bad sigma value"):
        weighted_price_deployer.deploy(10**9 - 1)
    with boa.reverts("bad sigma value"):
        weighted_price_deployer.deploy(WAD + 1)

    contract = weighted_price_deployer.deploy(WAD)
    assert contract.sigma() == WAD


def test_weighted_avg_simple_cases(weighted_price):
    assert weighted_price.weighted_avg([WAD, 2 * WAD], [WAD, WAD]) == 3 * WAD // 2
    assert weighted_price.weighted_avg([WAD, 2 * WAD], [3 * WAD, WAD]) == 5 * WAD // 4
    assert weighted_price.weighted_avg([7 * WAD], [123]) == 7 * WAD


def test_weighted_avg_reverts_on_bad_lengths_and_zero_weights(weighted_price):
    with boa.reverts("length mismatch"):
        weighted_price.weighted_avg([WAD], [WAD, WAD])

    with boa.reverts():
        weighted_price.weighted_avg([], [])

    with boa.reverts():
        weighted_price.weighted_avg([WAD, WAD], [0, 0])


def test_exp_penalized_price_identical_prices_invariant(weighted_price):
    price = 102 * WAD // 100

    assert weighted_price.exp_penalized_price(
        [price, price, price],
        [WAD // 2, WAD // 3, WAD // 6],
        WAD,
    ) == price


def test_exp_penalized_price_stays_in_source_range(weighted_price):
    prices = [90 * WAD // 100, WAD, 115 * WAD // 100]

    price = weighted_price.exp_penalized_price(
        prices,
        [WAD // 3, WAD // 3, WAD // 3],
        WAD,
    )

    assert min(prices) <= price <= max(prices)


def test_exp_penalty_is_symmetric_around_reference(weighted_price):
    price = weighted_price.exp_penalized_price(
        [90 * WAD // 100, 110 * WAD // 100],
        [WAD, WAD],
        WAD,
    )

    assert price == pytest.approx(WAD, rel=1e-18)


def test_smaller_sigma_penalizes_reference_outlier_more(weighted_price_deployer):
    narrow = weighted_price_deployer.deploy(10**16)
    wide = weighted_price_deployer.deploy(WAD)
    prices = [WAD, 120 * WAD // 100]
    weights = [WAD, WAD]

    narrow_price = narrow.exp_penalized_price(prices, weights, WAD)
    wide_price = wide.exp_penalized_price(prices, weights, WAD)

    assert WAD <= narrow_price <= wide_price <= 110 * WAD // 100
