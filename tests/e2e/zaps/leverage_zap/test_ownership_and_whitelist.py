"""
Tests for the LeverageZap admin (ownable) and exchange whitelist controls.

These deploy fresh zaps (not the shared module-scoped `leverage_zap` fixture) so
the constructor wiring — factory, admin and the initial exchange list, including
the events emitted at construction — can be asserted, and so that mutating the
admin / whitelist does not leak into the other test modules.
"""

import boa
import pytest

from tests.utils import filter_logs
from tests.utils.constants import ZERO_ADDRESS
from tests.utils.deployers import (
    LEVERAGE_ZAP_LENDING_DEPLOYER,
    LEVERAGE_ZAP_MINT_DEPLOYER,
)


def deploy_zap(market_type, factory, mint_factory, admin, exchanges):
    """Deploy a fresh zap for the current market type."""
    if market_type == "lending":
        return LEVERAGE_ZAP_LENDING_DEPLOYER.deploy(factory.address, admin, exchanges)
    return LEVERAGE_ZAP_MINT_DEPLOYER.deploy(mint_factory.address, admin, exchanges)


@pytest.fixture
def expected_factory(market_type, factory, mint_factory):
    return factory.address if market_type == "lending" else mint_factory.address


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_constructor_sets_factory_admin_exchanges(
    market_type, factory, mint_factory, expected_factory
):
    """factory, admin and the initial exchanges are wired up at deploy."""
    admin = boa.env.generate_address()
    ex1 = boa.env.generate_address()
    ex2 = boa.env.generate_address()

    zap = deploy_zap(market_type, factory, mint_factory, admin, [ex1, ex2])

    assert zap.FACTORY() == expected_factory
    assert zap.owner() == admin
    assert zap.is_approved_exchange(ex1) is True
    assert zap.is_approved_exchange(ex2) is True
    # An address that was not passed is not approved
    assert zap.is_approved_exchange(boa.env.generate_address()) is False


def test_constructor_emits_events(market_type, factory, mint_factory):
    """Constructor emits OwnershipTransferred -> admin and a SetExchange per exchange."""
    admin = boa.env.generate_address()
    ex1 = boa.env.generate_address()
    ex2 = boa.env.generate_address()

    zap = deploy_zap(market_type, factory, mint_factory, admin, [ex1, ex2])

    set_logs = filter_logs(zap, "SetExchange")
    assert [(log.exchange, log.approved) for log in set_logs] == [
        (ex1, True),
        (ex2, True),
    ]

    # ownable.__init__ assigns ownership to the deployer, then it is transferred to admin
    own_logs = filter_logs(zap, "OwnershipTransferred")
    assert own_logs[-1].new_owner == admin


def test_constructor_empty_exchanges(market_type, factory, mint_factory):
    """An empty exchange list is allowed and emits no SetExchange events."""
    admin = boa.env.generate_address()

    zap = deploy_zap(market_type, factory, mint_factory, admin, [])

    assert zap.owner() == admin
    assert filter_logs(zap, "SetExchange") == []


def test_constructor_max_exchanges(market_type, factory, mint_factory):
    """The maximum of 10 exchanges can be supplied at construction."""
    admin = boa.env.generate_address()
    exchanges = [boa.env.generate_address() for _ in range(10)]

    zap = deploy_zap(market_type, factory, mint_factory, admin, exchanges)

    for ex in exchanges:
        assert zap.is_approved_exchange(ex) is True


def test_constructor_zero_admin_reverts(market_type, factory, mint_factory):
    """A zero admin is rejected at construction."""
    with boa.reverts():
        deploy_zap(market_type, factory, mint_factory, ZERO_ADDRESS, [])


# ---------------------------------------------------------------------------
# set_exchange
# ---------------------------------------------------------------------------


def test_set_exchange_approve_and_revoke(market_type, factory, mint_factory):
    admin = boa.env.generate_address()
    zap = deploy_zap(market_type, factory, mint_factory, admin, [])
    exchange = boa.env.generate_address()
    assert zap.is_approved_exchange(exchange) is False

    # Approve (read logs before any view call resets the captured computation)
    with boa.env.prank(admin):
        zap.set_exchange(exchange, True)
    logs = filter_logs(zap, "SetExchange")
    assert len(logs) == 1
    assert logs[0].exchange == exchange
    assert logs[0].approved is True
    assert zap.is_approved_exchange(exchange) is True

    # Revoke
    with boa.env.prank(admin):
        zap.set_exchange(exchange, False)
    logs = filter_logs(zap, "SetExchange")
    assert len(logs) == 1
    assert logs[0].exchange == exchange
    assert logs[0].approved is False
    assert zap.is_approved_exchange(exchange) is False


def test_set_exchange_only_admin(market_type, factory, mint_factory):
    admin = boa.env.generate_address()
    zap = deploy_zap(market_type, factory, mint_factory, admin, [])
    exchange = boa.env.generate_address()

    with boa.env.prank(boa.env.generate_address()):
        with boa.reverts("ownable: caller is not the owner"):
            zap.set_exchange(exchange, True)
    assert zap.is_approved_exchange(exchange) is False


# ---------------------------------------------------------------------------
# transfer_ownership
# ---------------------------------------------------------------------------


def test_transfer_ownership(market_type, factory, mint_factory):
    admin = boa.env.generate_address()
    new_admin = boa.env.generate_address()
    zap = deploy_zap(market_type, factory, mint_factory, admin, [])

    with boa.env.prank(admin):
        zap.transfer_ownership(new_admin)
    logs = filter_logs(zap, "OwnershipTransferred")
    assert len(logs) == 1
    assert logs[0].previous_owner == admin
    assert logs[0].new_owner == new_admin
    assert zap.owner() == new_admin


def test_transfer_ownership_old_owner_loses_rights(market_type, factory, mint_factory):
    admin = boa.env.generate_address()
    new_admin = boa.env.generate_address()
    zap = deploy_zap(market_type, factory, mint_factory, admin, [])

    with boa.env.prank(admin):
        zap.transfer_ownership(new_admin)

    exchange = boa.env.generate_address()

    # Old owner can no longer manage the whitelist or ownership
    with boa.env.prank(admin):
        with boa.reverts("ownable: caller is not the owner"):
            zap.set_exchange(exchange, True)
        with boa.reverts("ownable: caller is not the owner"):
            zap.transfer_ownership(admin)

    # New admin can
    with boa.env.prank(new_admin):
        zap.set_exchange(exchange, True)
    assert zap.is_approved_exchange(exchange) is True


def test_transfer_ownership_only_owner(market_type, factory, mint_factory):
    admin = boa.env.generate_address()
    zap = deploy_zap(market_type, factory, mint_factory, admin, [])

    with boa.env.prank(boa.env.generate_address()):
        with boa.reverts("ownable: caller is not the owner"):
            zap.transfer_ownership(boa.env.generate_address())
    assert zap.owner() == admin


def test_transfer_ownership_zero_address_reverts(market_type, factory, mint_factory):
    admin = boa.env.generate_address()
    zap = deploy_zap(market_type, factory, mint_factory, admin, [])

    with boa.env.prank(admin):
        with boa.reverts("ownable: new owner is the zero address"):
            zap.transfer_ownership(ZERO_ADDRESS)
    assert zap.owner() == admin
