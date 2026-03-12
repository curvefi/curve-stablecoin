import boa
import pytest
from eth_abi import encode

from tests.utils.constants import WAD, MAX_UINT256
from tests.utils.deployers import (
    LEVERAGE_ZAP_LENDING_DEPLOYER,
    LEVERAGE_ZAP_MINT_DEPLOYER,
    DUMMY_ROUTER_DEPLOYER,
)


# ---------------------------------------------------------------------------
# Pure helper functions (no fixtures)
# ---------------------------------------------------------------------------


def collateral_from_borrowed(amount_in, price, borrowed_decimals, collateral_decimals):
    """Compute raw collateral out for raw borrowed_in at price (WAD-scaled borrowed-per-collateral)."""
    borrowed_precision = 10 ** (18 - borrowed_decimals)
    collateral_precision = 10 ** (18 - collateral_decimals)
    return amount_in * borrowed_precision * WAD // (price * collateral_precision)


def borrowed_from_collateral(amount_in, price, borrowed_decimals, collateral_decimals):
    """Compute raw borrowed out for raw collateral_in at price."""
    borrowed_precision = 10 ** (18 - borrowed_decimals)
    collateral_precision = 10 ** (18 - collateral_decimals)
    return amount_in * collateral_precision * price // (WAD * borrowed_precision)


def calc_p_avg(in_borrowed, out_collateral, borrowed_decimals, collateral_decimals):
    """Compute _p_avg (WAD-scaled borrowed-per-collateral) from raw swap amounts."""
    borrowed_precision = 10 ** (18 - borrowed_decimals)
    collateral_precision = 10 ** (18 - collateral_decimals)
    return (
        in_borrowed
        * borrowed_precision
        * WAD
        // (out_collateral * collateral_precision)
    )


def make_deposit_calldata(
    controller_id,
    user_borrowed,
    min_recv,
    router,
    borrowed_token,
    collateral_token,
    total_borrowed_in,
    collateral_out,
):
    """Encode calldata for callback_deposit: (controller_id, user_borrowed, min_recv, exchange_address, exchange_calldata)."""
    exchange_data = router.exchange.prepare_calldata(
        borrowed_token.address,
        collateral_token.address,
        total_borrowed_in,
        collateral_out,
    )
    return encode(
        ["uint256", "uint256", "uint256", "address", "bytes"],
        [controller_id, user_borrowed, min_recv, router.address, exchange_data],
    )


def make_repay_calldata(
    controller_id,
    user_collateral_amount,
    user_borrowed,
    min_recv,
    router,
    collateral_token,
    borrowed_token,
    total_collateral_in,
    borrowed_out,
):
    """Encode calldata for callback_repay: (controller_id, user_collateral, user_borrowed, min_recv, exchange_address, exchange_calldata)."""
    exchange_data = router.exchange.prepare_calldata(
        collateral_token.address,
        borrowed_token.address,
        total_collateral_in,
        borrowed_out,
    )
    return encode(
        ["uint256", "uint256", "uint256", "uint256", "address", "bytes"],
        [
            controller_id,
            user_collateral_amount,
            user_borrowed,
            min_recv,
            router.address,
            exchange_data,
        ],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def seed_liquidity(borrowed_token):
    return 10**6 * 10 ** borrowed_token.decimals()


@pytest.fixture(scope="module")
def borrow_cap(seed_liquidity):
    return seed_liquidity


@pytest.fixture(scope="module")
def leverage_zap(market_type, factory, mint_factory):
    if market_type == "lending":
        return LEVERAGE_ZAP_LENDING_DEPLOYER.deploy(factory.address)
    else:
        return LEVERAGE_ZAP_MINT_DEPLOYER.deploy(mint_factory.address)


@pytest.fixture(scope="module")
def dummy_router(borrowed_token, collateral_token):
    router = DUMMY_ROUTER_DEPLOYER.deploy()
    boa.deal(borrowed_token, router.address, 10**9 * 10 ** borrowed_token.decimals())
    boa.deal(
        collateral_token, router.address, 10**9 * 10 ** collateral_token.decimals()
    )
    return router


@pytest.fixture(scope="module")
def controller_id(market_type, factory, mint_factory, controller):
    if market_type == "lending":
        for i in range(factory.market_count()):
            mkt = factory.markets(i)
            ctrl = mkt.controller if hasattr(mkt, "controller") else mkt[1]
            ctrl_addr = ctrl.address if hasattr(ctrl, "address") else ctrl
            if ctrl_addr == controller.address:
                return i
    else:
        for i in range(mint_factory.n_collaterals()):
            if mint_factory.controllers(i) == controller.address:
                return i
    raise ValueError("Controller not found in factory")


@pytest.fixture
def open_position(
    controller,
    collateral_token,
    borrowed_token,
    leverage_zap,
    dummy_router,
    controller_id,
    price_oracle,
):
    """Create a leveraged position via zap and return a factory that generates borrower addresses."""

    def _open():
        borrower = boa.env.generate_address()
        bd = borrowed_token.decimals()
        cd = collateral_token.decimals()

        user_collateral = 2 * 10**cd
        d_debt = 3000 * 10**bd
        price = price_oracle.price()
        collateral_out = collateral_from_borrowed(d_debt, price, bd, cd)
        calldata = make_deposit_calldata(
            controller_id,
            0,
            collateral_out,
            dummy_router,
            borrowed_token,
            collateral_token,
            d_debt,
            collateral_out,
        )

        boa.deal(collateral_token, borrower, 10**6 * 10**cd)
        boa.deal(borrowed_token, borrower, 10**6 * 10**bd)
        with boa.env.prank(borrower):
            collateral_token.approve(controller.address, MAX_UINT256)
            collateral_token.approve(leverage_zap.address, MAX_UINT256)
            borrowed_token.approve(leverage_zap.address, MAX_UINT256)
            controller.create_loan(
                user_collateral, d_debt, 10, borrower, leverage_zap.address, calldata
            )
        return borrower

    return _open
