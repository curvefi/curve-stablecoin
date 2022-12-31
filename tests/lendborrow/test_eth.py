import boa
import pytest
from ..conftest import approx


# +++ WETH-specific fixtures +++
@pytest.fixture(scope="module")
def market(controller_factory, weth, monetary_policy, price_oracle, admin):
    with boa.env.prank(admin):
        if controller_factory.n_collaterals() == 0:
            controller_factory.add_market(
                weth.address, 100, 10**16, 0,
                price_oracle.address,
                monetary_policy.address, 5 * 10**16, 2 * 10**16,
                10**6 * 10**18)
        return controller_factory


@pytest.fixture(scope="module")
def market_amm(market, weth, stablecoin, amm_impl, amm_interface, accounts):
    amm = amm_interface.at(market.get_amm(weth.address))
    for acc in accounts:
        with boa.env.prank(acc):
            weth.approve(amm.address, 2**256-1)
            stablecoin.approve(amm.address, 2**256-1)
    return amm


@pytest.fixture(scope="module")
def market_controller(market, stablecoin, weth, controller_impl, controller_interface, controller_factory, accounts):
    controller = controller_interface.at(market.get_controller(weth.address))
    for acc in accounts:
        with boa.env.prank(acc):
            weth.approve(controller.address, 2**256-1)
            stablecoin.approve(controller.address, 2**256-1)
    return controller
# ^^^ WETH-specific fixtures ^^^


def test_create_loan(stablecoin, weth, market_controller, market_amm, accounts):
    user = accounts[0]
    assert market_controller.collateral_token() == weth.address

    with boa.env.anchor():
        with boa.env.prank(user):
            initial_amount = 10**25
            boa.env.set_balance(user, initial_amount)
            c_amount = int(2 * 1e6 * 1e18 * 1.5 / 3000)

            l_amount = 2 * 10**6 * 10**18
            with boa.reverts():
                market_controller.create_loan(c_amount, l_amount, 5, value=c_amount)

            l_amount = 5 * 10**5 * 10**18
            with boa.reverts('Need more ticks'):
                market_controller.create_loan(c_amount, l_amount, 4, value=c_amount)
            with boa.reverts('Need less ticks'):
                market_controller.create_loan(c_amount, l_amount, 400, value=c_amount)

            with boa.reverts("Debt too high"):
                market_controller.create_loan(c_amount // 100, l_amount, 5, value=c_amount // 100)

            # Phew, the loan finally was created
            market_controller.create_loan(c_amount, l_amount, 5, value=c_amount)
            # But cannot do it again
            with boa.reverts('Loan already created'):
                market_controller.create_loan(c_amount, 1, 5, value=c_amount)

            assert stablecoin.balanceOf(user) == l_amount
            assert l_amount == stablecoin.totalSupply() - stablecoin.balanceOf(market_controller)
            assert boa.env.get_balance(user) == initial_amount - c_amount

            assert market_controller.total_debt() == l_amount
            assert market_controller.debt(user) == l_amount

            p_up, p_down = market_controller.user_prices(user)
            p_lim = l_amount / c_amount / (1 - market_controller.loan_discount()/1e18)
            assert approx(p_lim, (p_down * p_up)**0.5 / 1e18, 2 / market_amm.A())

            h = market_controller.health(user) / 1e18 + 0.02
            assert h >= 0.05 and h <= 0.06

            h = market_controller.health(user, True) / 1e18 + 0.02
            assert approx(h, c_amount * 3000 / l_amount - 1, 0.02)
