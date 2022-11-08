import brownie
from brownie import ZERO_ADDRESS
import pytest


AMOUNT = 10**21


@pytest.fixture(autouse=True)
def mint(alice, bob, stablecoin):
    stablecoin.mint(alice, AMOUNT, {"from": alice})


def test_burn(alice, stablecoin):
    tx = stablecoin.burn(AMOUNT, {"from": alice})

    assert stablecoin.balanceOf(alice) == 0
    assert stablecoin.totalSupply() == 0
    assert tx.events["Transfer"].values() == [alice, ZERO_ADDRESS, AMOUNT]
    assert tx.return_value is True


def test_burn_reverts_insufficient_balance(alice, stablecoin):
    with brownie.reverts():
        stablecoin.burn(AMOUNT + 1, {"from": alice})


def test_burnFrom(alice, bob, stablecoin):
    stablecoin.approve(bob, AMOUNT, {"from": alice})
    tx = stablecoin.burnFrom(alice, AMOUNT, {"from": bob})

    assert stablecoin.balanceOf(alice) == 0
    assert stablecoin.totalSupply() == 0
    assert tx.events["Transfer"].values() == [alice, ZERO_ADDRESS, AMOUNT]

    assert stablecoin.allowance(alice, bob) == 0
    assert tx.events["Approval"].values() == [alice, bob, 0]
    assert tx.return_value is True


def test_burnFrom_with_infinite_allowance(alice, bob, stablecoin):
    stablecoin.approve(bob, 2**256 -1, {"from": alice})
    tx = stablecoin.burnFrom(alice, AMOUNT, {"from": bob})

    assert stablecoin.balanceOf(alice) == 0
    assert stablecoin.totalSupply() == 0
    assert tx.events["Transfer"].values() == [alice, ZERO_ADDRESS, AMOUNT]

    assert stablecoin.allowance(alice, bob) == 2**256 -1
    assert "Approval" not in tx.events
    assert tx.return_value is True


def test_burnFrom_reverts_insufficient_allowance(alice, bob, stablecoin):
    with brownie.reverts():
        stablecoin.burnFrom(alice, AMOUNT, {"from": bob})


def test_burnFrom_reverts_insufficient_balance(alice, bob, stablecoin):
    stablecoin.approve(bob, 2**256 -1, {"from": alice})

    with brownie.reverts():
        stablecoin.burnFrom(alice, AMOUNT + 1, {"from": bob})