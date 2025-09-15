import boa
from tests.utils.deployers import AMM_DEPLOYER, LL_CONTROLLER_DEPLOYER


def test_stablecoin_admin(controller_factory, stablecoin, accounts):
    with boa.env.anchor():
        assert stablecoin.minter().lower() == controller_factory.address.lower()
        with boa.reverts():
            with boa.env.prank(accounts[0]):
                stablecoin.set_minter(accounts[1])
        with boa.env.prank(controller_factory.address):
            stablecoin.set_minter(accounts[1])


def test_stablecoin(controller_factory, stablecoin):
    assert controller_factory.stablecoin() == stablecoin.address


def test_impl(controller_factory, controller_impl, amm_impl):
    assert controller_factory.controller_implementation() == controller_impl.address
    assert controller_factory.amm_implementation() == amm_impl.address


def test_add_market(
    controller_factory, collateral_token, price_oracle, monetary_policy, admin
):
    # token: address, A: uint256, fee: uint256, admin_fee: uint256,
    # _price_oracle_contract: address,
    # monetary_policy: address, loan_discount: uint256, liquidation_discount: uint256,
    # debt_ceiling: uint256) -> address[2]:
    with boa.env.anchor():
        with boa.env.prank(admin):
            controller_factory.add_market(
                collateral_token.address,
                100,
                10**16,
                0,
                price_oracle.address,
                monetary_policy.address,
                5 * 10**16,
                2 * 10**16,
                10**8 * 10**18,
            )

            assert controller_factory.n_collaterals() == 1
            assert (
                controller_factory.collaterals(0).lower()
                == collateral_token.address.lower()
            )

            controller = LL_CONTROLLER_DEPLOYER.at(
                controller_factory.get_controller(collateral_token.address)
            )
            amm = AMM_DEPLOYER.at(controller_factory.get_amm(collateral_token.address))

            assert controller.factory().lower() == controller_factory.address.lower()
            assert (
                controller.collateral_token().lower()
                == collateral_token.address.lower()
            )
            assert controller.amm().lower() == amm.address.lower()
            assert (
                controller.monetary_policy().lower() == monetary_policy.address.lower()
            )
            assert controller.liquidation_discount() == 2 * 10**16
            assert controller.loan_discount() == 5 * 10**16
            assert controller_factory.debt_ceiling(controller) == 10**8 * 10**18

            assert amm.admin().lower() == controller.address.lower()
            assert amm.A() == 100
            assert amm.price_oracle_contract().lower() == price_oracle.address.lower()
            assert amm.coins(1).lower() == collateral_token.address.lower()
