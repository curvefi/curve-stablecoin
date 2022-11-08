from brownie import ZERO_ADDRESS
import brownie
import pytest


AMOUNT = 10**21


@pytest.fixture(autouse=True)
def mint(alice, stablecoin):
    stablecoin.mint(alice, AMOUNT, {"from": alice})


def test_transfer(alice, bob, stablecoin):
    tx = stablecoin.transfer(bob, AMOUNT, {"from": alice})

    assert stablecoin.balanceOf(alice) == 0
    assert stablecoin.balanceOf(bob) == AMOUNT
    assert stablecoin.totalSupply() == AMOUNT  # unchanged
    assert tx.events["Transfer"].values() == [alice, bob, AMOUNT]
    assert tx.return_value is True


@pytest.mark.parametrize("idx", [0, 1])
def test_transfer_reverts_invalid_receipient(alice, stablecoin, idx):
    receiver = [ZERO_ADDRESS, stablecoin][idx]
    
    with brownie.reverts():
        stablecoin.transfer(receiver, AMOUNT, {"from": alice})


def test_transfer_reverts_insufficient_balance(alice, bob, stablecoin):
    with brownie.reverts():
        stablecoin.transfer(bob, AMOUNT + 1, {"from": alice})



def test_transferFrom(alice, bob, stablecoin):
    stablecoin.approve(bob, AMOUNT, {"from": alice})
    tx = stablecoin.transferFrom(alice, bob, AMOUNT, {"from": bob})

    assert stablecoin.balanceOf(alice) == 0
    assert stablecoin.balanceOf(bob) == AMOUNT
    assert tx.events["Transfer"].values() == [alice, bob, AMOUNT]

    assert stablecoin.allowance(alice, bob) == 0
    assert tx.events["Approval"].values() == [alice, bob, 0]
    assert tx.return_value is True


def test_transferFrom_with_infinite_allowance(alice, bob, stablecoin):
    stablecoin.approve(bob, 2**256 -1, {"from": alice})
    tx = stablecoin.transferFrom(alice, bob, AMOUNT, {"from": bob})

    assert stablecoin.balanceOf(alice) == 0
    assert stablecoin.balanceOf(bob) == AMOUNT
    assert tx.events["Transfer"].values() == [alice, bob, AMOUNT]

    assert stablecoin.allowance(alice, bob) == 2**256 -1
    assert "Approval" not in tx.events
    assert tx.return_value is True


def test_transferFrom_reverts_insufficient_allowance(alice, bob, stablecoin):
    with brownie.reverts():
        stablecoin.transferFrom(alice, bob, AMOUNT, {"from": bob})


def test_transferFrom_reverts_insufficient_balance(alice, bob, stablecoin):
    stablecoin.approve(bob, 2**256 - 1, {"from": alice})
    with brownie.reverts():
        stablecoin.transferFrom(alice, bob, AMOUNT + 1, {"from": bob})

