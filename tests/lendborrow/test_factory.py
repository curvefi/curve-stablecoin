import brownie


def test_stablecoin_admin(controller_factory, stablecoin, accounts):
    assert stablecoin.minters(controller_factory)
    assert not stablecoin.minters(accounts[0])
    with brownie.reverts():
        assert stablecoin.set_minter(accounts[1], True, {'from': accounts[0]})
    f = brownie.accounts.at(controller_factory, force=True)
    stablecoin.set_minter(accounts[1], True, {'from': f})
    stablecoin.set_minter(accounts[1], False, {'from': f})
