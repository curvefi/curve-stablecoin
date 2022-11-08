from brownie import ZERO_ADDRESS, accounts
import brownie
import boa

from eth_account._utils.structured_data.hashing import hash_domain, hash_message
from copy import deepcopy
from eth_account.messages import SignableMessage
from eth_account import Account as EthAccount




AMOUNT = 10**21

PERMIT_STRUCT = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
            {"name": "salt", "type": "bytes32"}
        ],
        "Permit": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "nonce", "type": "uint256"},
            {"name": "deadline", "type": "uint256"},
        ],
    },
    "primaryType": "Permit",
}



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

def test_permit_success(stablecoin, chain):
    alice = accounts.add("0x416b8a7d9290502f5661da81f0cf43893e3d19cb9aea3c426cfb36e8186e9c09")

    struct = deepcopy(PERMIT_STRUCT)
    struct["domain"] = dict(
        name=stablecoin.name(),
        version=stablecoin.version(),
        chainId=chain.id,
        verifyingContract=stablecoin.address,
        salt=stablecoin.salt(),
    )
    deadline = chain.time() + 600
    struct["message"] = dict(
        owner=alice.address,
        spender=alice.address,
        value=2**256 -1,
        nonce=stablecoin.nonces(alice),
        deadline=deadline,
    )
    signable_message = SignableMessage(
        b"\x01",
        hash_domain(struct),
        hash_message(struct)
    )
    sig = EthAccount.sign_message(signable_message, alice.private_key)
    
    tx = stablecoin.permit(alice, alice, 2**256 -1, deadline, sig.v, sig.r, sig.s)

    assert stablecoin.nonces(alice) == 1
    assert stablecoin.allowance(alice, alice) == 2**256 -1
    assert tx.events["Approval"].values() == [alice, alice, 2**256 -1]
    assert tx.return_value is True


def test_permit_reverts_owner_is_invalid(bob, chain, stablecoin):
    with brownie.reverts():
        stablecoin.permit(ZERO_ADDRESS, bob, 2**256 - 1, chain.time() + 600, 27, b"\x00" * 32, b"\x00" * 32, {"from": bob})


def test_permit_reverts_deadline_is_invalid(bob, chain, stablecoin):
    with brownie.reverts():
        stablecoin.permit(bob, bob, 2**256 - 1, chain.time() - 600, 27, b"\x00" * 32, b"\x00" * 32, {"from": bob})


def test_permit_reverts_signature_is_invalid(bob, chain, stablecoin):
    with brownie.reverts():
        stablecoin.permit(bob, bob, 2**256 - 1, chain.time() + 600, 27, b"\x00" * 32, b"\x00" * 32, {"from": bob})


def test_domain_separator_updates_when_chain_id_updates():
    stablecoin = boa.load("contracts/Stablecoin.vy", "CurveFi USD Stablecoin", "crvUSD")

    domain_separator = stablecoin.DOMAIN_SEPARATOR()
    with boa.env.anchor():
        boa.env.vm.patch.chain_id = 42
        assert domain_separator != stablecoin.DOMAIN_SEPARATOR()