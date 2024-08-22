import boa
import pytest


@pytest.fixture(scope="module")
def crv(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20CRV.vy', "Curve DAO Token", "CRV", 18)


@pytest.fixture(scope="module")
def voting_escrow(admin, crv):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/VotingEscrow.vy', crv, "Voting-escrowed CRV", "veCRV", "veCRV_0.99")


@pytest.fixture(scope="module")
def voting_escrow_delegation_mock(admin, voting_escrow):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/VEDelegationMock.vy', voting_escrow)


@pytest.fixture(scope="module")
def gauge_controller(admin, crv, voting_escrow):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/GaugeController.vy', crv, voting_escrow)


@pytest.fixture(scope="module")
def minter(admin, crv, gauge_controller):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/Minter.vy', crv, gauge_controller)


# Trader
@pytest.fixture(scope="module")
def chad(collateral_token, admin):
    _chad = boa.env.generate_address()
    collateral_token._mint_for_testing(_chad, 10**25, sender=admin)

    return _chad


@pytest.fixture(scope="module")
def stablecoin(admin, chad):
    with boa.env.prank(admin):
        _stablecoin = boa.load('contracts/Stablecoin.vy', 'Curve USD', 'crvUSD')
        _stablecoin.mint(chad, 10**25)

        return _stablecoin


@pytest.fixture(scope="module")
def weth(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/WETH.vy')


@pytest.fixture(scope="module")
def controller_prefactory(stablecoin, weth, admin, accounts):
    with boa.env.prank(admin):
        return boa.load('contracts/ControllerFactory.vy', stablecoin.address, admin, accounts[0], weth.address)


@pytest.fixture(scope="module")
def controller_interface():
    return boa.load_partial('contracts/Controller.vy')


@pytest.fixture(scope="module")
def controller_impl(controller_prefactory, controller_interface, admin):
    with boa.env.prank(admin):
        return controller_interface.deploy_as_blueprint()


@pytest.fixture(scope="module")
def amm_interface():
    return boa.load_partial('contracts/AMM.vy')


@pytest.fixture(scope="module")
def amm_impl(stablecoin, amm_interface, admin):
    with boa.env.prank(admin):
        return amm_interface.deploy_as_blueprint()


@pytest.fixture(scope="module")
def controller_factory(controller_prefactory, amm_impl, controller_impl, stablecoin, admin):
    with boa.env.prank(admin):
        controller_prefactory.set_implementations(controller_impl.address, amm_impl.address)
        stablecoin.set_minter(controller_prefactory.address)
    return controller_prefactory


@pytest.fixture(scope="module")
def monetary_policy(admin):
    with boa.env.prank(admin):
        policy = boa.load('contracts/testing/ConstantMonetaryPolicy.vy', admin)
        policy.set_rate(0)
        return policy


@pytest.fixture(scope="module")
def get_market(controller_factory, monetary_policy, price_oracle, stablecoin, accounts, admin, chad):
    def f(collateral_token):
        with boa.env.prank(admin):
            if controller_factory.n_collaterals() == 0:
                controller_factory.add_market(
                    collateral_token.address, 100, 10**16, 0,
                    price_oracle.address,
                    monetary_policy.address, 5 * 10**16, 2 * 10**16,
                    10**8 * 10**18)
                amm = controller_factory.get_amm(collateral_token.address)
                controller = controller_factory.get_controller(collateral_token.address)
                for acc in accounts:
                    with boa.env.prank(acc):
                        collateral_token.approve(amm, 2**256-1)
                        stablecoin.approve(amm, 2**256-1)
                        collateral_token.approve(controller, 2**256-1)
                        stablecoin.approve(controller, 2**256-1)
                with boa.env.prank(chad):
                    collateral_token.approve(amm, 2 ** 256 - 1)
                    stablecoin.approve(amm, 2 ** 256 - 1)
            return controller_factory
    return f


@pytest.fixture(scope="module")
def market(get_market, collateral_token):
    return get_market(collateral_token)


@pytest.fixture(scope="module")
def market_amm(market, collateral_token, stablecoin, amm_interface, accounts):
    return amm_interface.at(market.get_amm(collateral_token.address))


@pytest.fixture(scope="module")
def market_controller(market, stablecoin, collateral_token, controller_interface, controller_factory, accounts):
    return controller_interface.at(market.get_controller(collateral_token.address))


@pytest.fixture(scope="module")
def boosted_lm_callback(admin, controller_factory, collateral_token, crv, voting_escrow,
                        voting_escrow_delegation_mock, gauge_controller, minter, market_controller):
    with boa.env.prank(admin):
        cb = boa.load('contracts/BoostedLMCallback.vy', controller_factory, collateral_token, 0, crv,
                      voting_escrow, voting_escrow_delegation_mock, gauge_controller, minter)
        cb.initialize()
        market_controller.set_callback(cb)

        return cb


@pytest.fixture(scope="module")
def block_counter(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/BlockCounter.vy')
