import boa
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, invariant, initialize
from datetime import timedelta


class StatefulExchange(RuleBasedStateMachine):
    amounts = st.lists(st.floats(min_value=0, max_value=10**6), min_size=5, max_size=5)
    ns = st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5)
    dns = st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5)
    amount = st.floats(min_value=0, max_value=10**9)
    pump = st.booleans()
    user_id = st.integers(min_value=0, max_value=4)

    def __init__(self):
        super().__init__()
        self.total_deposited = 0
        self.collateral_decimals = self.collateral_token.decimals()
        self.borrowed_decimals = self.borrowed_token.decimals()

    @initialize(amounts=amounts, ns=ns, dns=dns)
    def initializer(self, amounts, ns, dns):
        amounts = list(map(lambda x: int(x * 10**self.collateral_decimals), amounts))
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
        self.initial_price = self.amm.price_oracle()

    @rule(amount=amount, pump=pump, user_id=user_id)
    def exchange(self, amount, pump, user_id):
        amount = int(amount * 10**self.collateral_decimals)
        u = self.accounts[user_id]
        if pump:
            i = 0
            j = 1
            in_token = self.borrowed_token
        else:
            i = 1
            j = 0
            in_token = self.collateral_token
        u_amount = in_token.balanceOf(u)
        required_amount = self.amm.get_dx(i, j, amount)
        if required_amount > u_amount:
            in_token._mint_for_testing(u, required_amount - u_amount)
        with boa.env.prank(u):
            self.amm.exchange_dy(i, j, amount, required_amount)

    @invariant()
    def amm_solvent(self):
        X = sum(self.amm.bands_x(n) for n in range(42))
        Y = sum(self.amm.bands_y(n) for n in range(42))
        assert self.borrowed_token.balanceOf(self.amm) * 10**(self.collateral_decimals - self.borrowed_decimals) >= X
        assert self.collateral_token.balanceOf(self.amm) >= Y

    @invariant()
    def dy_back(self):
        n = self.amm.active_band()
        to_receive = self.total_deposited * self.initial_price  # Huge amount
        left_in_amm = sum(self.amm.bands_y(n) for n in range(42))
        if n < 50:
            dx = self.amm.get_dx(1, 0, to_receive)
            assert dx >= self.total_deposited - left_in_amm  # With fees, AMM will have more

    def teardown(self):
        u = self.accounts[0]
        # Trade back and do the check
        n = self.amm.active_band()
        to_receive = self.total_deposited * self.initial_price  # Huge amount
        if n < 50:
            dy, dx = self.amm.get_dydx(1, 0, to_receive)
            if dy > 0:
                self.collateral_token._mint_for_testing(u, dx)
                with boa.env.prank(u):
                    self.amm.exchange_dy(1, 0, to_receive, dx)
                left_in_amm = sum(self.amm.bands_y(n) for n in range(42))
                assert left_in_amm >= self.total_deposited


def test_exchange(admin, accounts, amm, collateral_token, borrowed_token):
    with boa.env.anchor():
        StatefulExchange.TestCase.settings = settings(deadline=timedelta(seconds=1000))
        accounts = accounts[:5]
        for k, v in locals().items():
            setattr(StatefulExchange, k, v)
        run_state_machine_as_test(StatefulExchange)


def test_raise_at_dy_back(admin, accounts, amm, collateral_token, borrowed_token):
    StatefulExchange.TestCase.settings = settings(deadline=timedelta(seconds=1000))
    accounts = accounts[:5]
    for k, v in locals().items():
        setattr(StatefulExchange, k, v)
    state = StatefulExchange()
    state.initializer(amounts=[0.0, 0.0, 0.0, 1.0, 1.0], ns=[1, 1, 1, 1, 2], dns=[0, 0, 0, 0, 0])
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=1.0, pump=True, user_id=0)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=1.0, pump=True, user_id=0)
    state.amm_solvent()
    state.dy_back()
    state.teardown()
