from decimal import Decimal

from hypothesis import assume
from hypothesis import note
from hypothesis.strategies import (
    SearchStrategy,
    composite,
    decimals,
    integers,
    builds,
)

from tests.utils.constants import (
    MAX_UINT256,
    MIN_A,
    MAX_A,
    MIN_AMM_FEE,
    WAD,
    MIN_TICKS,
    MAX_TICKS,
)
from tests.utils.deployers import (
    AMM_DEPLOYER,
    CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER,
    ERC20_MOCK_DEPLOYER,
)
from tests.utils.protocols import Llamalend

DEBT_CEILING_MAX = 10**8 * 10**18  # TODO this has to go
STATEFUL_MAX_BORROWABLE_HAIRCUT = WAD - 10**15


As = integers(min_value=MIN_A, max_value=MAX_A)


def amm_fees_for_A(a: int):
    return integers(min_value=MIN_AMM_FEE, max_value=min(WAD * 4 // a, 10**17))


# Debt ceiling is a uint256 on-chain; generate as an integer
debt_ceilings = integers(min_value=0, max_value=DEBT_CEILING_MAX)
token_decimals = integers(min_value=2, max_value=18)
prices = integers(min_value=int(1e12), max_value=int(1e24))

# A simple strategy to initialize Llamalend using Hypothesis builds
protocols = builds(Llamalend, initial_price=prices)

# A simple strategy to deploy a collateral token with fuzzed decimals
collaterals = builds(ERC20_MOCK_DEPLOYER.deploy, token_decimals)


def token_amounts(
    decimal_places: int, min_value: int = 0, max_value: int = None
) -> SearchStrategy[int]:
    decs = decimals(
        min_value=min_value,
        max_value=max_value,
        allow_nan=False,
        allow_infinity=False,
        places=decimal_places,
    )

    def strip_point_to_int(d: Decimal) -> int:
        t = d.as_tuple()
        digits = "".join(map(str, t.digits)) or "0"
        zeros = "0" * max(t.exponent, 0)
        return int(digits + zeros)

    return decs.map(strip_point_to_int)


@composite
def discounts(draw):
    """Draw (loan_discount, liquidation_discount) with loan > liquidation."""
    liq = draw(integers(min_value=1, max_value=WAD - 2))
    loan = draw(
        integers(
            min_value=(liq + 1),
            max_value=WAD - 1,
        )
    )
    return loan, liq


@composite
def stateful_discounts(draw):
    """
    Draw realistic lending discounts for stateful tests.

    The broad `discounts()` strategy is still useful for unit fuzzing, but
    near-100% loan discounts make constructive stateful loan generation spend
    too much time proving that no borrowable debt exists.
    """
    liq = draw(integers(min_value=10**15, max_value=15 * 10**16))
    loan = draw(integers(min_value=liq + 1, max_value=50 * 10**16))
    return loan, liq


@composite
def mint_markets(
    draw,
    As=As,
    discounts=discounts(),
    debt_ceilings=debt_ceilings,
    initial_prices=prices,
):
    _A = draw(As)
    _fee = draw(amm_fees_for_A(_A))
    _loan_discount, _liq_discount = draw(discounts)
    _dc = draw(debt_ceilings)
    _price = draw(initial_prices)

    proto = Llamalend(initial_price=_price)

    _collateral = draw(collaterals)
    _dec = _collateral.decimals()

    market = proto.create_mint_market(
        collateral_token=_collateral,
        price_oracle=proto.price_oracle,
        monetary_policy=proto.mint_monetary_policy,
        A=_A,
        amm_fee=_fee,
        loan_discount=_loan_discount,
        liquidation_discount=_liq_discount,
        debt_ceiling=_dc,
    )

    note(
        "deployed mint market with "
        + f"A={_A}, fee={_fee}, loan_discount={_loan_discount}, liq_discount={_liq_discount}, debt_ceiling={_dc}"
        + f"; decimals={_dec}, price={_price}"
    )

    return market


@composite
def lend_markets(
    draw,
    As=As,
    discounts=stateful_discounts(),
    initial_prices=prices,
):
    _A = draw(As)
    _fee = draw(amm_fees_for_A(_A))
    _loan_discount, _liq_discount = draw(discounts)
    _price = draw(initial_prices)

    proto = Llamalend(initial_price=_price, deploy_mint=False)

    _borrowed_token = draw(collaterals)
    _collateral_token = draw(collaterals)
    _seed_amount = 10**6 * 10 ** int(_borrowed_token.decimals())

    market = proto.create_lending_market(
        borrowed_token=_borrowed_token,
        collateral_token=_collateral_token,
        A=_A,
        fee=_fee,
        loan_discount=_loan_discount,
        liquidation_discount=_liq_discount,
        price_oracle=proto.price_oracle,
        min_borrow_rate=0,
        max_borrow_rate=MAX_UINT256,
        seed_amount=_seed_amount,
    )
    proto.configurator.set_borrow_cap(
        market["controller"], _seed_amount, sender=proto.admin
    )
    market["configurator"] = proto.configurator
    market["monetary_policy"] = CONSTANT_MONETARY_POLICY_LENDING_DEPLOYER.at(
        market["controller"].monetary_policy()
    )

    note(
        "deployed lend market with "
        + f"A={_A}, fee={_fee}, loan_discount={_loan_discount}, liq_discount={_liq_discount}"
        + f"; price={_price}, seed_amount={_seed_amount}, borrow_cap={_seed_amount}"
    )

    return market


@composite
def loan_amounts_for_create(draw, controller, N: int) -> tuple[int, int]:
    """
    Draw a (collateral, debt) pair valid for Controller.create_loan given N.
    """
    collateral_token = ERC20_MOCK_DEPLOYER.at(controller.collateral_token())
    token_decs = collateral_token.decimals()

    collateral = draw(token_amounts(token_decs, min_value=1, max_value=1_000_000))
    view_cap = (
        int(controller.max_borrowable(collateral, N))
        * STATEFUL_MAX_BORROWABLE_HAIRCUT
        // WAD
    )

    loan_discount = controller.loan_discount()
    ltv = max(WAD - loan_discount, 0)

    borrowed_token = ERC20_MOCK_DEPLOYER.at(controller.borrowed_token())
    borrowed_decs = borrowed_token.decimals()
    col_prec = 10 ** (18 - int(token_decs))
    bor_prec = 10 ** (18 - int(borrowed_decs))

    price = AMM_DEPLOYER.at(controller.amm()).price_oracle()

    collateral_value_18 = (collateral * col_prec * price) // WAD
    ltv_cap_18 = (collateral_value_18 * ltv) // WAD
    ltv_cap = ltv_cap_18 // bor_prec

    available = int(controller.available_balance())
    try:
        cap_headroom = max(
            int(controller.borrow_cap()) - int(controller.total_debt()), 0
        )
    except Exception:
        cap_headroom = MAX_UINT256

    max_debt = min(view_cap, ltv_cap, available, cap_headroom)
    assume(max_debt > 0)

    min_debt = max(10 ** int(borrowed_decs), max_debt // 32)
    assume(max_debt >= min_debt)
    debt = draw(integers(min_value=min_debt, max_value=max_debt))
    return collateral, debt


@composite
def loan_increments_for_borrow_more(
    draw,
    controller,
    user: str,
    N: int,
) -> tuple[int, int]:
    """
    Draw (d_collateral, d_debt) increments for a safe borrow_more call.
    """
    collateral_token = ERC20_MOCK_DEPLOYER.at(controller.collateral_token())
    token_decs = collateral_token.decimals()

    d_collateral = draw(token_amounts(token_decs, min_value=1, max_value=1_000_000))

    delta_cap = (
        int(controller.max_borrowable(d_collateral, N, user))
        * STATEFUL_MAX_BORROWABLE_HAIRCUT
        // WAD
    )
    available = int(controller.available_balance())
    try:
        cap_headroom = max(
            int(controller.borrow_cap()) - int(controller.total_debt()), 0
        )
    except Exception:
        cap_headroom = MAX_UINT256
    delta_cap = min(delta_cap, available, cap_headroom)
    assume(delta_cap > 0)
    borrowed_token = ERC20_MOCK_DEPLOYER.at(controller.borrowed_token())
    min_delta = max(10 ** int(borrowed_token.decimals()), delta_cap // 32)
    assume(delta_cap >= min_delta)
    d_debt = draw(integers(min_value=min_delta, max_value=delta_cap))

    return d_collateral, d_debt


ticks = integers(min_value=MIN_TICKS, max_value=MAX_TICKS)
