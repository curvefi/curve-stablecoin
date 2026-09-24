"""
Tests for the capability the transient zap was built to provide: exchange calldata that
does not have to fit through the controller.

The older LeverageZap passes its swap parameters to the controller, which caps them at
`CALLDATA_MAX_SIZE` (32 * 300 bytes) before handing them on to the callback. Aggregator
routes regularly exceed that. This zap is the entry point instead and parks the
parameters in transient storage, so the only limit left is its own
`EXCHANGE_CALLDATA_MAX_SIZE` (32 * 1000 bytes).

Nothing else in the suite passes calldata larger than a bare `exchange(...)` call, so
the whole point of the contract is untested. These tests read both limits from the
contracts themselves rather than restating them, so they keep meaning what they say if
either constant moves.
"""

import boa
import pytest

from tests.utils.deployers import (
    CONSTANTS_DEPLOYER,
    TRANSIENT_LEVERAGE_ZAP_CONSTANTS_DEPLOYER,
    PADDED_ROUTER_DEPLOYER,
)

from tests.e2e.zaps.transient_leverage_zap.conftest import (
    approve_zap,
    borrowed_from_collateral,
    collateral_from_borrowed,
)

N = 10


@pytest.fixture(scope="module")
def zap_calldata_max():
    """The zap's own cap, from the constants module both zap flavours share."""
    return TRANSIENT_LEVERAGE_ZAP_CONSTANTS_DEPLOYER.deploy().eval(
        "EXCHANGE_CALLDATA_MAX_SIZE"
    )


@pytest.fixture(scope="module")
def controller_calldata_max():
    """The cap the controller puts on callback calldata, straight from constants.vy."""
    return CONSTANTS_DEPLOYER.deploy().eval("CALLDATA_MAX_SIZE")


@pytest.fixture(scope="module")
def padded_router(borrowed_token, collateral_token, leverage_zap, admin):
    router = PADDED_ROUTER_DEPLOYER.deploy()
    boa.deal(borrowed_token, router.address, 10**9 * 10 ** borrowed_token.decimals())
    boa.deal(
        collateral_token, router.address, 10**9 * 10 ** collateral_token.decimals()
    )
    with boa.env.prank(admin):
        leverage_zap.set_exchange(router.address, True)
    return router


@pytest.fixture
def borrower(controller, collateral_token, borrowed_token, leverage_zap):
    user = boa.env.generate_address()
    boa.deal(collateral_token, user, 10**6 * 10 ** collateral_token.decimals())
    boa.deal(borrowed_token, user, 10**6 * 10 ** borrowed_token.decimals())
    approve_zap(user, controller, leverage_zap, collateral_token, borrowed_token)
    return user


def route_of(n_bytes):
    """A deterministic blob standing in for an aggregator route."""
    return bytes((i % 251) for i in range(n_bytes))


# ---------------------------------------------------------------------------
# Past the controller's limit
# ---------------------------------------------------------------------------


def test_create_loan_with_route_larger_than_controller_limit(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    padded_router,
    controller_id,
    controller_calldata_max,
    price_oracle,
):
    """
    A route that the controller could not have carried goes through end to end, and
    arrives at the exchange byte for byte.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    collateral_out = collateral_from_borrowed(d_debt, price_oracle.price(), bd, cd)

    route = route_of(3 * controller_calldata_max)
    exchange_calldata = padded_router.exchange_with_route.prepare_calldata(
        borrowed_token.address,
        collateral_token.address,
        d_debt,
        collateral_out,
        route,
    )
    assert len(exchange_calldata) > controller_calldata_max

    with boa.env.prank(borrower):
        leverage_zap.create_loan(
            controller_id,
            user_collateral,
            d_debt,
            N,
            collateral_out * 999 // 1000,
            padded_router.address,
            exchange_calldata,
        )

    assert padded_router.last_route_size() == len(route)
    state = controller.user_state(borrower)
    assert state[0] == user_collateral + collateral_out
    assert state[2] == d_debt
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0


def test_repay_with_route_larger_than_controller_limit(
    open_position,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    padded_router,
    controller_id,
    controller_calldata_max,
    price_oracle,
):
    """The deleveraging side carries oversized routes too."""
    borrower = open_position()
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()

    state0 = controller.user_state(borrower)
    collateral_to_swap = state0[0] // 4
    borrowed_out = borrowed_from_collateral(
        collateral_to_swap, price_oracle.price(), bd, cd
    )

    route = route_of(3 * controller_calldata_max)
    exchange_calldata = padded_router.exchange_with_route.prepare_calldata(
        collateral_token.address,
        borrowed_token.address,
        collateral_to_swap,
        borrowed_out,
        route,
    )
    assert len(exchange_calldata) > controller_calldata_max

    with boa.env.prank(borrower):
        leverage_zap.repay(
            controller_id,
            0,
            collateral_to_swap,
            borrowed_out * 999 // 1000,
            padded_router.address,
            exchange_calldata,
        )

    assert padded_router.last_route_size() == len(route)
    state1 = controller.user_state(borrower)
    assert state1[0] == state0[0] - collateral_to_swap
    assert state1[2] == state0[2] - borrowed_out


# ---------------------------------------------------------------------------
# The zap's own limit
# ---------------------------------------------------------------------------


def test_exchange_calldata_at_zap_maximum_is_accepted(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    padded_router,
    controller_id,
    zap_calldata_max,
    price_oracle,
):
    """
    Exactly `EXCHANGE_CALLDATA_MAX_SIZE` bytes are accepted, forwarded whole, and the
    swap they drive settles normally.

    The blob is sized to the byte rather than ABI-encoded for a typed argument, since
    encoding only lands on 32-byte steps; the exchange's fallback performs a swap
    arranged beforehand and reports the number of bytes it was called with.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    collateral_out = collateral_from_borrowed(d_debt, price_oracle.price(), bd, cd)

    padded_router.set_next_swap(
        borrowed_token.address, collateral_token.address, d_debt, collateral_out
    )
    exchange_calldata = route_of(zap_calldata_max)
    assert len(exchange_calldata) == zap_calldata_max

    with boa.env.prank(borrower):
        leverage_zap.create_loan(
            controller_id,
            user_collateral,
            d_debt,
            N,
            collateral_out * 999 // 1000,
            padded_router.address,
            exchange_calldata,
        )

    assert padded_router.last_calldata_size() == zap_calldata_max
    state = controller.user_state(borrower)
    assert state[0] == user_collateral + collateral_out
    assert state[2] == d_debt


def test_exchange_calldata_over_zap_maximum_reverts(
    borrower,
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    padded_router,
    controller_id,
    zap_calldata_max,
    price_oracle,
):
    """
    One byte more is refused while decoding the arguments, before any of the zap's own
    logic runs - so the caller gets a rejection rather than a silently truncated route
    being executed against their funds.
    """
    bd = borrowed_token.decimals()
    cd = collateral_token.decimals()
    user_collateral = 2 * 10**cd
    d_debt = 3000 * 10**bd
    collateral_out = collateral_from_borrowed(d_debt, price_oracle.price(), bd, cd)

    padded_router.set_next_swap(
        borrowed_token.address, collateral_token.address, d_debt, collateral_out
    )

    with boa.env.prank(borrower):
        with boa.reverts():
            leverage_zap.create_loan(
                controller_id,
                user_collateral,
                d_debt,
                N,
                collateral_out * 999 // 1000,
                padded_router.address,
                route_of(zap_calldata_max + 1),
            )

    assert not controller.loan_exists(borrower)
    assert collateral_token.balanceOf(leverage_zap.address) == 0
    assert borrowed_token.balanceOf(leverage_zap.address) == 0
