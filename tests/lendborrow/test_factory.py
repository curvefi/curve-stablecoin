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
    assert controller_factory.stablecoin() == stablecoin.address


def test_add_market(controller_factory, collateral_token, PriceOracle, monetary_policy, accounts):
    # token: address, A: uint256, fee: uint256, admin_fee: uint256,
    # _price_oracle_contract: address,
    # monetary_policy: address, loan_discount: uint256, liquidation_discount: uint256,
    # debt_ceiling: uint256) -> address[2]:
    controller_factory.add_market(
        collateral_token, 100, 10**16, 0,
        PriceOracle,
        monetary_policy, 5 * 10**16, 2 * 10**16,
        10**8 * 10*18,
        {'from': accounts[0]})


def test_impl(controller_factory, controller_impl, amm_impl):
    assert controller_factory.controller_implementation() == controller_impl.address
    assert controller_factory.amm_implementation() == amm_impl.address
