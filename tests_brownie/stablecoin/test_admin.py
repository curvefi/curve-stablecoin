import brownie


def test_add_minter(alice, bob, stablecoin):
    tx = stablecoin.add_minter(bob, {"from": alice})

    assert stablecoin.is_minter(bob) is True
    assert tx.events["AddMinter"].values() == [bob]


def test_add_minter_reverts_invalid_caller(bob, stablecoin):
    with brownie.reverts():
        stablecoin.add_minter(bob, {"from": bob})


def test_remove_minter(alice, bob, stablecoin):
    stablecoin.add_minter(bob, {"from": alice})
    tx = stablecoin.remove_minter(bob, {"from": alice})

    assert stablecoin.is_minter(bob) is False
    assert tx.events["RemoveMinter"] == [bob]


def test_remove_minter_reverts_invalid_caller(bob, stablecoin):
    with brownie.reverts():
        stablecoin.remove_minter(bob, {"from": bob})


def test_set_admin(alice, bob, stablecoin):
    tx = stablecoin.set_admin(bob, {"from": alice})

    assert stablecoin.admin() == bob
    assert tx.events["SetAdmin"].values() == [bob]


def test_set_admin_reverts_invalid_caller(bob, stablecoin):
    with brownie.reverts():
        stablecoin.set_admin(bob, {"from": bob})
