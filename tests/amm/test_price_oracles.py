import boa
import pytest
from ..conftest import PRICE
from tests.utils.deployers import EMA_PRICE_ORACLE_DEPLOYER


@pytest.fixture(scope="module")
def ema_price_oracle(price_oracle, admin):
    with boa.env.prank(admin):
        selector4 = price_oracle.price.prepare_calldata()[:4]
        selector32 = selector4.rjust(32, b"\x00")
        return EMA_PRICE_ORACLE_DEPLOYER.deploy(10000, price_oracle.address, selector32)


def test_price_oracle(price_oracle, amm):
    assert price_oracle.price() == PRICE * 10**18
    assert amm.price_oracle() == price_oracle.price()


def test_p_oracle_updown(amm):
    p_base = amm.get_base_price()
    A = amm.A()
    assert amm.p_oracle_up(0) == p_base
    assert amm.p_oracle_down(0) == pytest.approx(p_base * (A - 1) // A, rel=1e-14)

    for i in range(-10, 10):
        mul = ((A - 1) / A) ** i
        p_up = p_base * mul
        p_down = p_up * (A - 1) / A
        assert amm.p_oracle_up(i) == pytest.approx(p_up, rel=1e-14)
        assert amm.p_oracle_down(i) == pytest.approx(p_down, rel=1e-14)


def test_p_current_updown(amm):
    p_base = amm.get_base_price()
    p_oracle = amm.price_oracle()
    A = amm.A()

    for i in range(-1023, 1023):
        mul = ((A - 1) / A) ** i
        p_base_up = p_base * mul
        p_base_down = p_base_up * (A - 1) / A
        p_current_up = p_oracle**3 / p_base_down**2
        p_current_down = p_oracle**3 / p_base_up**2
        assert amm.p_current_up(i) == pytest.approx(p_current_up, rel=1e-10)
        assert amm.p_current_down(i) == pytest.approx(p_current_down, rel=1e-10)


def test_ema_wrapping(ema_price_oracle, price_oracle):
    with boa.env.anchor():
        assert price_oracle.price() == ema_price_oracle.last_price()
        assert price_oracle.price() == ema_price_oracle.price()
        ema_price_oracle.price_w()
        boa.env.time_travel(20000)
        assert price_oracle.price() == ema_price_oracle.price()
        ema_price_oracle.price_w()
        boa.env.time_travel(20000)
        assert price_oracle.price() == ema_price_oracle.price()


def test_ema_sleep(ema_price_oracle, price_oracle, admin):
    with boa.env.anchor():
        p = price_oracle.price()
        with boa.env.prank(admin):
            price_oracle.set_price(p // 2)
        boa.env.time_travel(5)
        ema_price_oracle.price_w()
        boa.env.time_travel(1000000)
        assert (ema_price_oracle.price() - p // 2) < p / 10
