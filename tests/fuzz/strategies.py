from hypothesis import note
from hypothesis.strategies import (
    composite,
    integers,
    builds,
)

from tests.utils.constants import (
    MAX_UINT256,
    MIN_A,
    MAX_A,
    MIN_FEE,
    MAX_FEE,
    MAX_LOAN_DISCOUNT,
    MIN_LIQUIDATION_DISCOUNT,
    MIN_TICKS,
    MAX_TICKS,
)
from tests.utils.deployers import ERC20_MOCK_DEPLOYER
from tests.utils.protocols import Llamalend

DEBT_CEILING_MAX = 10**8 * 10**18  # TODO this has to go


As = integers(min_value=MIN_A, max_value=MAX_A)
amm_fees = integers(min_value=MIN_FEE, max_value=MAX_FEE)
# Debt ceiling is a uint256 on-chain; generate as an integer
debt_ceilings = integers(min_value=0, max_value=DEBT_CEILING_MAX)
token_decimals = integers(min_value=2, max_value=18)
prices = integers(min_value=int(1e12), max_value=int(1e24))

# A simple strategy to initialize Llamalend using Hypothesis builds
protocols = builds(Llamalend, initial_price=prices)

# A simple strategy to deploy a collateral token with fuzzed decimals
collaterals = builds(ERC20_MOCK_DEPLOYER.deploy, token_decimals)


@composite
def discounts(draw):
    """Draw (loan_discount, liquidation_discount) with loan > liquidation."""
    liq = draw(
        integers(min_value=MIN_LIQUIDATION_DISCOUNT, max_value=MAX_LOAN_DISCOUNT - 1)
    )
    loan = draw(
        integers(
            min_value=(max(liq, MIN_LIQUIDATION_DISCOUNT) + 1),
            max_value=MAX_LOAN_DISCOUNT,
        )
    )
    return loan, liq


@composite
def mint_markets(
    draw,
    As=As,
    amm_fees=amm_fees,
    discounts=discounts(),
    debt_ceilings=debt_ceilings,
    initial_prices=prices,
):
    _A = draw(As)
    _fee = draw(amm_fees)
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
        debt_ceiling=MAX_UINT256,
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
    amm_fees=amm_fees,
    discounts=discounts(),
    initial_prices=prices,
):
    _A = draw(As)
    _fee = draw(amm_fees)
    _loan_discount, _liq_discount = draw(discounts)
    _price = draw(initial_prices)

    proto = Llamalend(initial_price=_price)

    _borrowed_token = draw(collaterals)
    _collateral_token = draw(collaterals)

    market = proto.create_lending_market(
        borrowed_token=_borrowed_token,
        collateral_token=_collateral_token,
        A=_A,
        fee=_fee,
        loan_discount=_loan_discount,
        liquidation_discount=_liq_discount,
        price_oracle=proto.price_oracle,
        name="Fuzz Vault",
        min_borrow_rate=0,
        max_borrow_rate=MAX_UINT256,
        seed_amount=0,
    )

    note(
        "deployed lend market with "
        + f"A={_A}, fee={_fee}, loan_discount={_loan_discount}, liq_discount={_liq_discount}"
        + f"; price={_price}"
    )

    return market


# TODO eventually fix this in SC (actually maybe this was for A?)
ticks = integers(min_value=MIN_TICKS + 1, max_value=MAX_TICKS)
