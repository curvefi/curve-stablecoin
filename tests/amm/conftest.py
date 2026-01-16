import boa
import pytest
from math import sqrt, log
from tests.utils.deployers import AMM_DEPLOYER, ERC20_MOCK_DEPLOYER

BASE_PRICE = 3000


@pytest.fixture(scope="module")
def borrowed_token():
    return ERC20_MOCK_DEPLOYER.deploy(6)


@pytest.fixture(scope="module")
def get_amm(price_oracle, admin, accounts):
    def f(collateral_token, borrowed_token):
        with boa.env.prank(admin):
            amm = AMM_DEPLOYER.deploy(
                borrowed_token.address,
                10 ** (18 - borrowed_token.decimals()),
                collateral_token.address,
                10 ** (18 - collateral_token.decimals()),
                100,
                int(sqrt(100 / 99) * 1e18),
                int(log(100 / 99) * 1e18),
                BASE_PRICE * 10**18,
                10**16,
                0,
                price_oracle.address,
            )
            amm.set_admin(admin)
        for acct in accounts:
            with boa.env.prank(acct):
                collateral_token.approve(amm.address, 2**256 - 1)
                borrowed_token.approve(amm.address, 2**256 - 1)
        return amm

    return f


@pytest.fixture(scope="module")
def amm(collateral_token, borrowed_token, get_amm):
    return get_amm(collateral_token, borrowed_token)


@pytest.fixture(scope="module")
def get_price_oracle_band(price_oracle, amm):
    def f():
        A = amm.A()
        p_o = price_oracle.price()

        # p_o = BASE_PRICE * ((A - 1) / A)**band_p_o
        band_p_o = int(log(p_o / BASE_PRICE) / ((A - 1) / A))
        while amm.p_oracle_down(band_p_o) > p_o:
            band_p_o += 1

        return band_p_o

    return f
