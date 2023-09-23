import boa
import pytest
from hypothesis import settings
from hypothesis import HealthCheck
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant, initialize
from hypothesis import Phase


class StatefulExchange(RuleBasedStateMachine):
    amounts = st.lists(st.integers(min_value=0, max_value=10**6 * 10**18), min_size=5, max_size=5)
    ns = st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5)
    dns = st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5)
    amount = st.integers(min_value=0, max_value=10**9 * 10**18)
    pump = st.booleans()
    user_id = st.integers(min_value=0, max_value=4)
    admin_fee = st.integers(min_value=0, max_value=10**18)

    def __init__(self):
        super().__init__()
        self.total_deposited = 0

    @initialize(amounts=amounts, ns=ns, dns=dns)
    def initializer(self, amounts, ns, dns):
        self.borrowed_mul = 10**(18 - self.borrowed_digits)
        self.collateral_mul = 10**(18 - self.collateral_digits)
        amounts = [a // self.collateral_mul for a in amounts]
        for user, amount, n1, dn in zip(self.accounts, amounts, ns, dns):
            n2 = n1 + dn
            try:
                with boa.env.prank(self.admin):
                    self.amm.deposit_range(user, amount, n1, n2)
                    self.collateral_token._mint_for_testing(self.amm.address, amount)
            except Exception as e:
                if 'Amount too low' in str(e):
                    assert amount // (dn + 1) <= 100
                else:
                    raise
        self.total_deposited = sum(self.amm.bands_y(n) for n in range(42))

    @rule(amount=amount, pump=pump, user_id=user_id)
    def exchange(self, amount, pump, user_id):
        u = self.accounts[user_id]
        if pump:
            amount = amount // self.borrowed_mul
            i = 0
            j = 1
            in_token = self.borrowed_token
        else:
            amount = amount // self.collateral_mul
            i = 1
            j = 0
            in_token = self.collateral_token
        u_amount = in_token.balanceOf(u)
        if amount > u_amount:
            in_token._mint_for_testing(u, amount - u_amount)
        with boa.env.prank(u):
            self.amm.exchange(i, j, amount, 0)

    @rule(fee=admin_fee)
    def set_admin_fee(self, fee):
        with boa.env.prank(self.admin):
            self.amm.set_admin_fee(fee)

    @invariant()
    def amm_solvent(self):
        X = sum(self.amm.bands_x(n) for n in range(42))
        Y = sum(self.amm.bands_y(n) for n in range(42))
        assert self.borrowed_token.balanceOf(self.amm) * self.borrowed_mul >= X
        assert self.collateral_token.balanceOf(self.amm) * self.collateral_mul >= Y

    @invariant()
    def dy_back(self):
        n = self.amm.active_band()
        to_swap = self.total_deposited * 10 // self.collateral_mul
        left_in_amm = sum(self.amm.bands_y(n) for n in range(42))
        if n < 50:
            dx, dy = self.amm.get_dxdy(1, 0, to_swap)
            assert dx * self.collateral_mul >= self.total_deposited - left_in_amm  # With fees, AMM will have more

    def teardown(self):
        if not hasattr(self, 'amm'):
            return
        u = self.accounts[0]
        # Trade back and do the check
        n = self.amm.active_band()
        to_swap = self.total_deposited * 10 // self.collateral_mul
        if n < 50:
            _, dy = self.amm.get_dxdy(1, 0, to_swap)
            if dy > 0:
                self.collateral_token._mint_for_testing(u, to_swap)
                with boa.env.prank(u):
                    self.amm.exchange(1, 0, to_swap, 0)
                left_in_amm = sum(self.amm.bands_y(n) for n in range(42))
                assert left_in_amm >= self.total_deposited


@pytest.mark.parametrize("borrowed_digits", [6, 8, 18])
@pytest.mark.parametrize("collateral_digits", [6, 8, 18])
def test_exchange(admin, accounts, get_amm, get_collateral_token, get_borrowed_token,
                  borrowed_digits, collateral_digits):
    StatefulExchange.TestCase.settings = settings(max_examples=20, stateful_step_count=10,
                                                  phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target),
                                                  suppress_health_check=[HealthCheck.data_too_large])
    accounts = accounts[:5]

    borrowed_token = get_borrowed_token(borrowed_digits)
    collateral_token = get_collateral_token(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)
    run_state_machine_as_test(StatefulExchange)


def test_raise_at_dy_back(admin, accounts, get_amm, get_collateral_token, get_borrowed_token):
    accounts = accounts[:5]

    borrowed_digits = 18
    collateral_digits = 18

    borrowed_token = get_borrowed_token(borrowed_digits)
    collateral_token = get_collateral_token(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)
    state = StatefulExchange()
    state.initializer(amounts=[0, 0, 0, 10**18, 10**18], ns=[1, 1, 1, 1, 2], dns=[0, 0, 0, 0, 0])
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=3123061067055650168655, pump=True, user_id=0)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=3123061067055650168655, pump=True, user_id=0)
    state.amm_solvent()
    state.dy_back()
    state.teardown()


def test_raise_rounding(admin, accounts, get_amm, get_collateral_token, get_borrowed_token):
    accounts = accounts[:5]

    borrowed_digits = 16
    collateral_digits = 18

    borrowed_token = get_borrowed_token(borrowed_digits)
    collateral_token = get_collateral_token(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)
    state = StatefulExchange()
    state.initializer(amounts=[101, 0, 0, 0, 0], ns=[1, 1, 1, 1, 1], dns=[0, 0, 0, 0, 0])
    state.exchange(amount=100, pump=True, user_id=0)
    state.dy_back()
    state.teardown()


def test_raise_rounding_2(admin, accounts, get_amm, get_collateral_token, get_borrowed_token):
    accounts = accounts[:5]

    borrowed_digits = 18
    collateral_digits = 18

    borrowed_token = get_borrowed_token(borrowed_digits)
    collateral_token = get_collateral_token(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)
    state = StatefulExchange()
    state.initializer(amounts=[779, 5642, 768, 51924, 5], ns=[2, 3, 4, 10, 18], dns=[11, 12, 14, 15, 15])
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=42, pump=True, user_id=1)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=512, pump=True, user_id=2)
    state.amm_solvent()
    state.dy_back()
    state.teardown()


def test_raise_rounding_3(admin, accounts, get_amm, get_collateral_token, get_borrowed_token):
    accounts = accounts[:5]

    borrowed_digits = 17
    collateral_digits = 18

    borrowed_token = get_borrowed_token(borrowed_digits)
    collateral_token = get_collateral_token(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)
    state = StatefulExchange()
    state.initializer(amounts=[33477, 63887, 387, 1, 0], ns=[4, 18, 6, 19, 5], dns=[18, 0, 8, 20, 5])
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=22005, pump=False, user_id=2)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=184846817736507205598398482, pump=False, user_id=4)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=140, pump=True, user_id=2)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=233, pump=True, user_id=0)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=54618, pump=True, user_id=3)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=169, pump=True, user_id=3)
    state.amm_solvent()
    state.dy_back()
    state.teardown()
