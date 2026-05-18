import boa

from tests.utils.constants import MAX_A, MAX_FEE, MAX_UINT256, MIN_A, MIN_FEE
from tests.utils.deployers import AMM_DEPLOYER, DUMMY_PRICE_ORACLE_DEPLOYER
from tests.utils.deployers import LEND_CONTROLLER_DEPLOYER, VAULT_DEPLOYER


PRICE_ORACLE_MISMATCH_CODE = """
# pragma version 0.4.3

price: public(uint256)
price_w_value: public(uint256)


@deploy
def __init__(_price: uint256, _price_w: uint256):
    self.price = _price
    self.price_w_value = _price_w


@external
def price_w() -> uint256:
    return self.price_w_value
"""


def _deploy_mpolicy(
    lending_monetary_policy, borrowed_token, min_borrow_rate, max_borrow_rate
):
    return lending_monetary_policy.deploy(
        borrowed_token.address,
        min_borrow_rate,
        max_borrow_rate,
    )


def _create_market(
    factory,
    admin,
    borrowed_token,
    collateral_token,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    price_oracle,
    monetary_policy,
    supply_limit=MAX_UINT256,
):
    with boa.env.prank(admin):
        return factory.create(
            borrowed_token.address,
            collateral_token.address,
            amm_A,
            amm_fee,
            loan_discount,
            liquidation_discount,
            price_oracle.address,
            monetary_policy.address,
            supply_limit,
        )


def test_default_behavior_create_sets_relationships(
    factory,
    admin,
    borrowed_token,
    collateral_token,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    price_oracle,
    lending_monetary_policy,
    min_borrow_rate,
    max_borrow_rate,
):
    monetary_policy = _deploy_mpolicy(
        lending_monetary_policy, borrowed_token, min_borrow_rate, max_borrow_rate
    )

    result = _create_market(
        factory,
        admin,
        borrowed_token,
        collateral_token,
        amm_A,
        amm_fee,
        loan_discount,
        liquidation_discount,
        price_oracle,
        monetary_policy,
    )

    vault = VAULT_DEPLOYER.at(result[0])
    controller = LEND_CONTROLLER_DEPLOYER.at(result[1])
    amm = AMM_DEPLOYER.at(result[2])

    assert vault.amm() == amm.address
    assert vault.controller() == controller.address
    assert controller.vault() == vault.address
    assert controller.amm() == amm.address
    assert amm.admin() == controller.address


def test_revert_create_same_token(
    factory,
    admin,
    borrowed_token,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    price_oracle,
    lending_monetary_policy,
    min_borrow_rate,
    max_borrow_rate,
):
    monetary_policy = _deploy_mpolicy(
        lending_monetary_policy, borrowed_token, min_borrow_rate, max_borrow_rate
    )

    with boa.reverts("Same token"):
        _create_market(
            factory,
            admin,
            borrowed_token,
            borrowed_token,
            amm_A,
            amm_fee,
            loan_discount,
            liquidation_discount,
            price_oracle,
            monetary_policy,
        )


def test_revert_create_invalid_A(
    factory,
    admin,
    borrowed_token,
    collateral_token,
    amm_fee,
    loan_discount,
    liquidation_discount,
    price_oracle,
    lending_monetary_policy,
    min_borrow_rate,
    max_borrow_rate,
):
    monetary_policy = _deploy_mpolicy(
        lending_monetary_policy, borrowed_token, min_borrow_rate, max_borrow_rate
    )

    with boa.reverts("Wrong A"):
        _create_market(
            factory,
            admin,
            borrowed_token,
            collateral_token,
            MIN_A - 1,
            amm_fee,
            loan_discount,
            liquidation_discount,
            price_oracle,
            monetary_policy,
        )

    with boa.reverts("Wrong A"):
        _create_market(
            factory,
            admin,
            borrowed_token,
            collateral_token,
            MAX_A + 1,
            amm_fee,
            loan_discount,
            liquidation_discount,
            price_oracle,
            monetary_policy,
        )


def test_revert_create_invalid_fee(
    factory,
    admin,
    borrowed_token,
    collateral_token,
    amm_A,
    loan_discount,
    liquidation_discount,
    price_oracle,
    lending_monetary_policy,
    min_borrow_rate,
    max_borrow_rate,
):
    monetary_policy = _deploy_mpolicy(
        lending_monetary_policy, borrowed_token, min_borrow_rate, max_borrow_rate
    )

    with boa.reverts("Fee too low"):
        _create_market(
            factory,
            admin,
            borrowed_token,
            collateral_token,
            amm_A,
            MIN_FEE - 1,
            loan_discount,
            liquidation_discount,
            price_oracle,
            monetary_policy,
        )

    with boa.reverts("Fee too high"):
        _create_market(
            factory,
            admin,
            borrowed_token,
            collateral_token,
            amm_A,
            MAX_FEE + 1,
            loan_discount,
            liquidation_discount,
            price_oracle,
            monetary_policy,
        )


def test_revert_create_invalid_price_oracle_price_zero(
    factory,
    admin,
    borrowed_token,
    collateral_token,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    lending_monetary_policy,
    min_borrow_rate,
    max_borrow_rate,
):
    monetary_policy = _deploy_mpolicy(
        lending_monetary_policy, borrowed_token, min_borrow_rate, max_borrow_rate
    )
    price_oracle_zero = DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, 0)

    with boa.reverts(dev="price oracle returned zero"):
        _create_market(
            factory,
            admin,
            borrowed_token,
            collateral_token,
            amm_A,
            amm_fee,
            loan_discount,
            liquidation_discount,
            price_oracle_zero,
            monetary_policy,
        )


def test_revert_create_invalid_price_oracle_mismatch(
    factory,
    admin,
    borrowed_token,
    collateral_token,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    lending_monetary_policy,
    min_borrow_rate,
    max_borrow_rate,
):
    monetary_policy = _deploy_mpolicy(
        lending_monetary_policy, borrowed_token, min_borrow_rate, max_borrow_rate
    )
    oracle_deployer = boa.loads_partial(PRICE_ORACLE_MISMATCH_CODE)
    mismatch_oracle = oracle_deployer.deploy(3000 * 10**18, 3100 * 10**18)

    with boa.reverts(dev="price oracle price() and price_w() mismatch"):
        _create_market(
            factory,
            admin,
            borrowed_token,
            collateral_token,
            amm_A,
            amm_fee,
            loan_discount,
            liquidation_discount,
            mismatch_oracle,
            monetary_policy,
        )
