"""
Tests for the LeverageZap admin access control and exchange whitelist.

Access control is delegated to the factory: only `FACTORY.admin()` may manage
the exchange whitelist. These tests deploy fresh zaps (not the shared
module-scoped `leverage_zap` fixture) so the constructor wiring — factory and
the initial exchange list, including the events emitted at construction — can be
asserted, and so that mutating the whitelist does not leak into the other test
modules.
"""

import boa
import pytest

from tests.utils import filter_logs
from tests.utils.deployers import (
    LEVERAGE_ZAP_LENDING_DEPLOYER,
    LEVERAGE_ZAP_MINT_DEPLOYER,
)


def deploy_zap(market_type, factory, mint_factory, exchanges):
    """Deploy a fresh zap for the current market type."""
    if market_type == "lending":
        return LEVERAGE_ZAP_LENDING_DEPLOYER.deploy(factory.address, exchanges)
    return LEVERAGE_ZAP_MINT_DEPLOYER.deploy(mint_factory.address, exchanges)


@pytest.fixture
def expected_factory(market_type, factory, mint_factory):
    return factory.address if market_type == "lending" else mint_factory.address


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_constructor_sets_factory_exchanges(
    market_type, factory, mint_factory, expected_factory, admin
):
    """factory and the initial exchanges are wired up at deploy."""
    ex1 = boa.env.generate_address()
    ex2 = boa.env.generate_address()

    zap = deploy_zap(market_type, factory, mint_factory, [ex1, ex2])

    assert zap.FACTORY() == expected_factory
    # admin is delegated to the factory
    assert zap.admin() == admin
    assert zap.is_approved_exchange(ex1) is True
    assert zap.is_approved_exchange(ex2) is True
    # An address that was not passed is not approved
    assert zap.is_approved_exchange(boa.env.generate_address()) is False


def test_constructor_emits_events(market_type, factory, mint_factory):
    """Constructor emits a SetExchange per exchange."""
    ex1 = boa.env.generate_address()
    ex2 = boa.env.generate_address()

    zap = deploy_zap(market_type, factory, mint_factory, [ex1, ex2])

    set_logs = filter_logs(zap, "SetExchange")
    assert [(log.exchange, log.approved) for log in set_logs] == [
        (ex1, True),
        (ex2, True),
    ]


def test_constructor_empty_exchanges(market_type, factory, mint_factory):
    """An empty exchange list is allowed and emits no SetExchange events."""
    zap = deploy_zap(market_type, factory, mint_factory, [])

    assert filter_logs(zap, "SetExchange") == []


def test_constructor_max_exchanges(market_type, factory, mint_factory):
    """The maximum of 10 exchanges can be supplied at construction."""
    exchanges = [boa.env.generate_address() for _ in range(10)]

    zap = deploy_zap(market_type, factory, mint_factory, exchanges)

    for ex in exchanges:
        assert zap.is_approved_exchange(ex) is True


# ---------------------------------------------------------------------------
# set_exchange
# ---------------------------------------------------------------------------


def test_set_exchange_approve_and_revoke(market_type, factory, mint_factory, admin):
    zap = deploy_zap(market_type, factory, mint_factory, [])
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
    zap = deploy_zap(market_type, factory, mint_factory, [])
    exchange = boa.env.generate_address()

    with boa.env.prank(boa.env.generate_address()):
        with boa.reverts("Only admin"):
            zap.set_exchange(exchange, True)
    assert zap.is_approved_exchange(exchange) is False


def test_set_exchange_follows_factory_admin(market_type, factory, mint_factory, admin):
    """When the factory admin changes, access control follows it."""
    zap = deploy_zap(market_type, factory, mint_factory, [])
    exchange = boa.env.generate_address()
    new_admin = boa.env.generate_address()
    assert zap.admin() == admin

    with boa.env.prank(admin):
        if market_type == "lending":
            factory.transfer_ownership(new_admin)
        else:
            mint_factory.set_admin(new_admin)

    # The zap's admin now reflects the new factory admin
    assert zap.admin() == new_admin

    # Old admin can no longer manage the whitelist
    with boa.env.prank(admin):
        with boa.reverts("Only admin"):
            zap.set_exchange(exchange, True)

    # New factory admin can
    with boa.env.prank(new_admin):
        zap.set_exchange(exchange, True)
    assert zap.is_approved_exchange(exchange) is True
