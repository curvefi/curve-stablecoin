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


def test_increaseAllowance(alice, bob, stablecoin):
    tx = stablecoin.increaseAllowance(bob, AMOUNT, {"from": alice})

    assert stablecoin.allowance(alice, bob) == AMOUNT
    assert tx.events["Approval"].values() == [alice, bob, AMOUNT]
    assert tx.return_value is True


def test_increaseAllowance_does_not_overflow(alice, bob, stablecoin):
    for _ in range(10):
        stablecoin.increaseAllowance(bob, 2 ** 255 - 1, {"from": alice})
    
    assert stablecoin.allowance(alice, bob) == 2**256 -1
    
    tx = stablecoin.increaseAllowance(bob, 10, {"from": alice})
    assert "Approval" not in tx.events
    assert tx.return_value is True


def test_decreaseAllowance(alice, bob, stablecoin):
    stablecoin.approve(bob, AMOUNT, {"from": alice})
    tx = stablecoin.decreaseAllowance(bob, AMOUNT, {"from": alice})

    assert stablecoin.allowance(alice, bob) == 0
    assert tx.events["Approval"].values() == [alice, bob, 0]
    assert tx.return_value is True


def test_decreaseAllowance_does_not_underflow(alice, bob, stablecoin):
    for _ in range(10):
        stablecoin.decreaseAllowance(bob, 10, {"from": alice})
    
    assert stablecoin.allowance(alice, bob) == 0

    tx = stablecoin.decreaseAllowance(bob, 10, {"from": alice})

    assert "Approval" not in tx.events
    assert tx.return_value is True
