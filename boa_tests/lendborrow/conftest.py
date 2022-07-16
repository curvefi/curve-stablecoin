import boa
import pytest
from boa.contract import VyperContract


@pytest.fixture(scope="session", autouse=True)
def stablecoin(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/Stablecoin.vy', 'Curve USD', 'crvUSD')


@pytest.fixture(scope="session", autouse=True)
def controller_prefactory(stablecoin, admin, accounts):
    with boa.env.prank(admin):
        return boa.load('contracts/ControllerFactory.vy', stablecoin.address, admin, accounts[0])


@pytest.fixture(scope="session", autouse=True)
def controller_impl(controller_prefactory, admin):
    with boa.env.prank(admin):
        return boa.load('contracts/Controller.vy', controller_prefactory.address)


@pytest.fixture(scope="session", autouse=True)
def amm_impl(stablecoin, admin):
    with boa.env.prank(admin):
        return boa.load('contracts/AMM.vy', stablecoin.address)


@pytest.fixture(scope="session", autouse=True)
def controller_factory(controller_prefactory, amm_impl, controller_impl, stablecoin, admin):
    with boa.env.prank(admin):
        controller_prefactory.set_implementations(controller_impl.address, amm_impl.address)
        stablecoin.set_minter(controller_prefactory.address, True)
        stablecoin.set_minter(admin, False)
    return controller_prefactory


@pytest.fixture(scope="session", autouse=True)
def monetary_policy(admin):
    with boa.env.prank(admin):
        policy = boa.load('contracts/mpolicies/ConstantMonetaryPolicy.vy', admin)
        policy.set_rate(0)
        return policy


@pytest.fixture(scope="session", autouse=True)
def market(controller_factory, collateral_token, monetary_policy, price_oracle, admin):
    with boa.env.prank(admin):
        if controller_factory.n_collaterals() == 0:
            controller_factory.add_market(
                collateral_token.address, 100, 10**16, 0,
                price_oracle.address,
                monetary_policy.address, 5 * 10**16, 2 * 10**16,
                10**6 * 10**18)
        return controller_factory


@pytest.fixture(scope="session", autouse=True)
def market_amm(market, collateral_token, stablecoin, amm_impl):
    return VyperContract(
        amm_impl.compiler_data, stablecoin.address,
        override_address=bytes.fromhex(market.amms(collateral_token.address)[2:])
    )


@pytest.fixture(scope="session", autouse=True)
def market_controller(market, collateral_token, controller_impl, controller_factory, accounts):
    controller = VyperContract(
        controller_impl.compiler_data,
        controller_factory.address,
        override_address=collateral_token.address
    )
    for acc in accounts:
        with boa.env.prank(acc):
            collateral_token.approve(controller.address, 2**256-1)
    return controller
