import boa
import pytest
from vyper.utils import method_id
from tests.utils.deployers import (
    STABLECOIN_DEPLOYER,
    WETH_DEPLOYER,
    CONTROLLER_FACTORY_DEPLOYER,
    MINT_CONTROLLER_DEPLOYER,
    AMM_DEPLOYER,
    CONSTANT_MONETARY_POLICY_DEPLOYER,
    FAKE_LEVERAGE_DEPLOYER,
)


def get_method_id(desc):
    return method_id(desc).to_bytes(4, "big") + b"\x00" * 28


@pytest.fixture(scope="session")
def stablecoin_pre():
    return STABLECOIN_DEPLOYER


@pytest.fixture(scope="module")
def stablecoin(stablecoin_pre, admin):
    with boa.env.prank(admin):
        return stablecoin_pre.deploy("Curve USD", "crvUSD")


@pytest.fixture(scope="module")
def weth(admin):
    with boa.env.prank(admin):
        return WETH_DEPLOYER.deploy()


@pytest.fixture(scope="session")
def controller_factory_impl():
    return CONTROLLER_FACTORY_DEPLOYER


@pytest.fixture(scope="module")
def controller_prefactory(controller_factory_impl, stablecoin, weth, admin, accounts):
    with boa.env.prank(admin):
        return controller_factory_impl.deploy(
            stablecoin.address, admin, accounts[0], weth.address
        )


@pytest.fixture(scope="module")
def controller_impl(proto):
    return proto.blueprints.mint_controller


@pytest.fixture(scope="module")
def amm_impl(admin):
    with boa.env.prank(admin):
        return AMM_DEPLOYER.deploy_as_blueprint()


@pytest.fixture(scope="module")
def controller_factory(
    controller_prefactory, amm_impl, controller_impl, stablecoin, admin
):
    with boa.env.prank(admin):
        controller_prefactory.set_implementations(
            controller_impl.address, amm_impl.address
        )
        stablecoin.set_minter(controller_prefactory.address)
    return controller_prefactory


@pytest.fixture(scope="module")
def monetary_policy(admin):
    with boa.env.prank(admin):
        policy = CONSTANT_MONETARY_POLICY_DEPLOYER.deploy(admin)
        policy.set_rate(0)
        return policy


@pytest.fixture(scope="module")
def get_market(
    controller_factory, monetary_policy, price_oracle, stablecoin, accounts, admin
):
    def f(collateral_token):
        with boa.env.prank(admin):
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
                amm = controller_factory.get_amm(collateral_token.address)
                controller = controller_factory.get_controller(collateral_token.address)
                for acc in accounts:
                    with boa.env.prank(acc):
                        collateral_token.approve(amm, 2**256 - 1)
                        stablecoin.approve(amm, 2**256 - 1)
                        collateral_token.approve(controller, 2**256 - 1)
                        stablecoin.approve(controller, 2**256 - 1)
            return controller_factory

    return f


@pytest.fixture(scope="module")
def market(get_market, collateral_token):
    return get_market(collateral_token)


@pytest.fixture(scope="module")
def market_amm(market, collateral_token, stablecoin, accounts):
    return AMM_DEPLOYER.at(market.get_amm(collateral_token.address))


@pytest.fixture(scope="module")
def market_controller(market, stablecoin, collateral_token, accounts):
    return MINT_CONTROLLER_DEPLOYER.at(market.get_controller(collateral_token.address))


@pytest.fixture(scope="module")
def get_fake_leverage(stablecoin, admin):
    def f(collateral_token, market_controller):
        # Fake leverage testing contract can also be used to liquidate via the callback
        with boa.env.prank(admin):
            leverage = FAKE_LEVERAGE_DEPLOYER.deploy(
                stablecoin.address,
                collateral_token.address,
                market_controller.address,
                3000 * 10**18,
            )
            boa.deal(
                collateral_token,
                leverage.address,
                1000 * 10 ** collateral_token.decimals(),
            )
            return leverage

    return f


@pytest.fixture(scope="module")
def fake_leverage(get_fake_leverage, collateral_token, market_controller):
    return get_fake_leverage(collateral_token, market_controller)
