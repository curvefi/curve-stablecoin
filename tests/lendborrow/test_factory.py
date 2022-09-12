import brownie


def test_stablecoin_admin(controller_factory, stablecoin, accounts):
    assert stablecoin.minters(controller_factory)
    assert not stablecoin.minters(accounts[0])
    with brownie.reverts():
        assert stablecoin.set_minter(accounts[1], True, {'from': accounts[0]})
    f = brownie.accounts.at(controller_factory, force=True)
    stablecoin.set_minter(accounts[1], True, {'from': f})
    stablecoin.set_minter(accounts[1], False, {'from': f})


def test_stablecoin(controller_factory, stablecoin):
    assert controller_factory.stablecoin() == stablecoin


def test_impl(controller_factory, controller_impl, amm_impl):
    assert controller_factory.controller_implementation() == controller_impl
    assert controller_factory.amm_implementation() == amm_impl


def test_add_market(controller_factory, collateral_token, PriceOracle, monetary_policy, accounts,
                    Controller, AMM):
    # token: address, A: uint256, fee: uint256, admin_fee: uint256,
    # _price_oracle_contract: address,
    # monetary_policy: address, loan_discount: uint256, liquidation_discount: uint256,
    # debt_ceiling: uint256) -> address[2]:
    controller_factory.add_market(
        collateral_token, 100, 10**16, 0,
        PriceOracle,
        monetary_policy, 5 * 10**16, 2 * 10**16,
        10**8 * 10**18,
        {'from': accounts[0]})

    assert controller_factory.n_collaterals() == 1
    assert controller_factory.collaterals(0) == collateral_token

    controller = Controller.at(controller_factory.get_controller(collateral_token))
    amm = AMM.at(controller_factory.get_amm(collateral_token))

    assert controller.factory() == controller_factory
    assert controller.collateral_token() == collateral_token
    assert controller.amm() == amm
    assert controller.monetary_policy() == monetary_policy
    assert controller.liquidation_discount() == 2 * 10**16
    assert controller.loan_discount()  == 5 * 10**16
    assert controller_factory.debt_ceiling(controller) == 10**8 * 10**18

    assert amm.admin() == controller
    assert amm.A() == 100
    assert amm.price_oracle_contract() == PriceOracle
    assert amm.collateral_token() == collateral_token
