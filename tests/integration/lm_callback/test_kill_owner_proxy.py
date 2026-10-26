"""Minimal lending proxy model for factory-owner kill permissions."""

import boa
import pytest
from eth_abi import encode
from eth_utils import keccak


OWNER_PROXY = """
# pragma version 0.4.3
interface IGauge:
    def set_killed(killed: bool): nonpayable

dao: address
emergency_dao: address

@deploy
def __init__(_dao: address, _emergency_dao: address):
    self.dao = _dao
    self.emergency_dao = _emergency_dao

@external
def set_killed(gauge: IGauge):
    assert msg.sender in [self.dao, self.emergency_dao], "Unauthorized"
    extcall gauge.set_killed(True)

@external
def execute(target: address, data: Bytes[1024]):
    assert msg.sender == self.dao, "Only DAO"
    raw_call(target, data)

@external
def set_emergency_dao(emergency_dao: address):
    assert msg.sender == self.dao, "Only DAO"
    self.emergency_dao = emergency_dao
"""


@pytest.fixture(scope="module")
def owner_proxy(admin):
    emergency_dao = boa.env.generate_address("emergency_dao")
    return boa.loads(OWNER_PROXY, admin, emergency_dao), emergency_dao


def test_proxy_kills_and_only_dao_resumes(
    admin, lm_callback, lm_callback_factory, owner_proxy
):
    with boa.env.anchor():
        proxy, emergency_dao = owner_proxy
        with boa.reverts("only owner"):
            proxy.set_killed(lm_callback.address, sender=emergency_dao)

        lm_callback_factory.transfer_ownership(proxy.address, sender=admin)
        proxy.set_killed(lm_callback.address, sender=emergency_dao)
        assert lm_callback.is_killed()
        with boa.reverts("only owner"):
            lm_callback.set_killed(False, sender=emergency_dao)

        resume = keccak(text="set_killed(bool)")[:4] + encode(["bool"], [False])
        with boa.reverts("Only DAO"):
            proxy.execute(lm_callback.address, resume, sender=emergency_dao)
        proxy.execute(lm_callback.address, resume, sender=admin)
        assert not lm_callback.is_killed()


def test_proxy_emergency_rotation_and_revocation(
    admin, lm_callback, lm_callback_factory, owner_proxy
):
    with boa.env.anchor():
        proxy, emergency_dao = owner_proxy
        lm_callback_factory.transfer_ownership(proxy.address, sender=admin)
        new_emergency_dao = boa.env.generate_address("new_emergency_dao")
        with boa.reverts("Only DAO"):
            proxy.set_emergency_dao(new_emergency_dao, sender=emergency_dao)
        proxy.set_emergency_dao(new_emergency_dao, sender=admin)
        with boa.reverts("Unauthorized"):
            proxy.set_killed(lm_callback.address, sender=emergency_dao)
        proxy.set_killed(lm_callback.address, sender=new_emergency_dao)

        proxy.set_emergency_dao("0x" + "00" * 20, sender=admin)
        with boa.reverts("Unauthorized"):
            proxy.set_killed(lm_callback.address, sender=new_emergency_dao)
