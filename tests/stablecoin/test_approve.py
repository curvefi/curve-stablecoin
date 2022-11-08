from brownie import ZERO_ADDRESS

AMOUNT = 10**21


def test_approve(alice, bob, stablecoin):
    tx = stablecoin.approve(bob, AMOUNT, {"from": alice})

    assert stablecoin.allowance(alice, bob) == AMOUNT
    assert tx.events["Approval"].values() == [alice, bob, AMOUNT]
    assert tx.return_value is True


def test_nonzero_to_nonzero_approval(alice, bob, stablecoin):
    stablecoin.approve(bob, 20, {"from": alice})
    tx = stablecoin.approve(bob, AMOUNT, {"from": alice})

    assert stablecoin.allowance(alice, bob) == AMOUNT
    assert tx.events["Approval"].values() == [alice, bob, AMOUNT]
    assert tx.return_value is True
