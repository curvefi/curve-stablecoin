import pytest
from vyper.utils import abi_method_id
from ..utils import deploy_test_blueprint


def get_method_id(desc):
    return abi_method_id(desc).to_bytes(4, "big") + b"\x00" * 28


@pytest.fixture(scope="module")
def stablecoin(project, forked_admin):
    return forked_admin.deploy(project.Stablecoin, "Curve USD", "crvUSD")


@pytest.fixture(scope="module")
def controller_prefactory(project, forked_admin, stablecoin, weth, forked_fee_receiver):
    return forked_admin.deploy(
        project.ControllerFactory,
        stablecoin.address,
        forked_admin,
        forked_fee_receiver,
        weth.address,
    )


@pytest.fixture(scope="module")
def controller_impl(project, forked_admin):
    return deploy_test_blueprint(project, project.Controller, forked_admin)


@pytest.fixture(scope="module")
def amm_impl(project, forked_admin):
    return deploy_test_blueprint(project, project.AMM, forked_admin)


@pytest.fixture(scope="module")
def controller_factory(forked_admin, controller_prefactory, amm_impl, controller_impl, stablecoin):
    controller_prefactory.set_implementations(controller_impl, amm_impl, sender=forked_admin)
    stablecoin.set_minter(controller_prefactory.address, sender=forked_admin)
    return controller_prefactory


@pytest.fixture(scope="module")
def monetary_policy(project, forked_admin):
    policy = forked_admin.deploy(project.ConstantMonetaryPolicy, forked_admin)
    policy.set_rate(0, sender=forked_admin)
    return policy


@pytest.fixture(scope="module")
def market(controller_factory, collateral_token, monetary_policy, price_oracle, forked_admin):
    if controller_factory.n_collaterals() == 0:
        controller_factory.add_market(
            collateral_token.address,
            100,
            10**16,
            0,
            price_oracle.address,
            monetary_policy.address,
            5 * 10**16,
            2 * 10**16,
            10**6 * 10**18,
        )
    return controller_factory


@pytest.fixture(scope="module")
def market_amm(market, collateral_token, stablecoin, amm_impl, amm_interface, accounts):
    amm = amm_interface.at(market.get_amm(collateral_token.address))
    for acc in accounts:
        collateral_token.approve(amm.address, 2**256 - 1, sender=acc)
        stablecoin.approve(amm.address, 2**256 - 1, sender=acc)
    return amm


@pytest.fixture(scope="module")
def market_controller(
    market,
    stablecoin,
    collateral_token,
    controller_interface,
    accounts,
):
    controller = controller_interface.at(market.get_controller(collateral_token.address))
    for acc in accounts:
        collateral_token.approve(controller.address, 2**256 - 1, sender=acc)
        stablecoin.approve(controller.address, 2**256 - 1, sender=acc)
    return controller


@pytest.fixture(scope="module")
def fake_leverage(project, forked_admin, stablecoin, collateral_token, market_controller):
    # Fake leverage testing contract can also be used to liquidate via the callback
    leverage = forked_admin.deploy(
        project.FakeLeverage,
        stablecoin.address,
        collateral_token.address,
        market_controller.address,
        3000 * 10**18,
    )
    collateral_token._mint_for_testing(leverage.address, 1000 * 10**18)
    return leverage


@pytest.fixture(scope="module")
def unsafe_factory(forked_admin, controller_factory):
    # Give admin ability to mint coins for testing (don't do that at home!)
    controller_factory.set_debt_ceiling(forked_admin, 10**6 * 10**18, sender=forked_admin)
    yield controller_factory
