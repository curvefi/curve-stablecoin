import pytest

from tests.utils.constants import MAX_ORACLE_PRICE_DEVIATION, MAX_UINT256, WAD
from tests.utils.deployers import DUMMY_PRICE_ORACLE_DEPLOYER


@pytest.fixture
def deploy_price_oracle(admin):
    def _deploy_price_oracle(price):
        return DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, price, sender=admin)

    return _deploy_price_oracle


@pytest.fixture
def current_amm_price_oracle(amm):
    return DUMMY_PRICE_ORACLE_DEPLOYER.at(amm.price_oracle_contract())


def test_set_price_oracle_updates_amm_price_oracle(
    configurator, controller, amm, price_oracle, admin, deploy_price_oracle
):
    new_oracle = deploy_price_oracle(price_oracle.price())

    assert amm.price_oracle_contract() != new_oracle.address

    configurator.set_price_oracle(controller, new_oracle, 0, sender=admin)

    assert amm.price_oracle_contract() == new_oracle.address


def test_set_price_oracle_accepts_max_deviation_boundary(
    configurator, controller, amm, price_oracle, admin, deploy_price_oracle
):
    current_oracle = amm.price_oracle_contract()
    boundary_price = price_oracle.price() * (WAD + MAX_ORACLE_PRICE_DEVIATION) // WAD
    boundary_oracle = deploy_price_oracle(boundary_price)

    configurator.set_price_oracle(
        controller, boundary_oracle, MAX_ORACLE_PRICE_DEVIATION, sender=admin
    )

    assert current_oracle != boundary_oracle.address
    assert amm.price_oracle_contract() == boundary_oracle.address


def test_set_price_oracle_allows_higher_new_price_within_limit(
    configurator, controller, amm, admin, current_amm_price_oracle, deploy_price_oracle
):
    old_price = current_amm_price_oracle.price()
    max_delta = old_price * MAX_ORACLE_PRICE_DEVIATION // WAD
    higher_price = old_price + max_delta // 2
    higher_oracle = deploy_price_oracle(higher_price)

    delta = higher_oracle.price() - old_price
    assert 0 < delta < max_delta

    configurator.set_price_oracle(
        controller, higher_oracle, MAX_ORACLE_PRICE_DEVIATION, sender=admin
    )

    assert amm.price_oracle_contract() == higher_oracle.address


def test_set_price_oracle_skips_deviation_check_with_max_uint(
    configurator, controller, amm, admin, current_amm_price_oracle, deploy_price_oracle
):
    current_price = current_amm_price_oracle.price()
    high_deviation_price = current_price * (WAD + MAX_ORACLE_PRICE_DEVIATION + 1) // WAD
    high_deviation_oracle = deploy_price_oracle(high_deviation_price)

    delta = high_deviation_oracle.price() - current_price
    max_delta = current_price * MAX_ORACLE_PRICE_DEVIATION // WAD
    assert delta > max_delta

    configurator.set_price_oracle(
        controller, high_deviation_oracle, MAX_UINT256, sender=admin
    )

    assert amm.price_oracle_contract() == high_deviation_oracle.address
