import boa
import pytest
from hypothesis import settings
from hypothesis import HealthCheck
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    run_state_machine_as_test,
    rule,
    invariant,
    initialize,
)
from hypothesis import Phase
from tests.amm.utils import deposit_amount_too_low
from tests.utils import mint_for_testing
from tests.utils.deployers import ERC20_MOCK_DEPLOYER


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

    @initialize(amounts=amounts, ns=ns, dns=dns, part=pump)
    def initializer(self, amounts, ns, dns, part=False):
        self.borrowed_mul = 10 ** (18 - self.borrowed_digits)
        self.collateral_mul = 10 ** (18 - self.collateral_digits)
        amounts = list(map(lambda x: int(x * 10**self.collateral_digits), amounts))
        for user, amount, n1, dn in zip(self.users, amounts, ns, dns):
            n2 = n1 + dn
            with boa.env.prank(user):
                self.collateral_token.approve(self.amm.address, 2**256 - 1)
                self.borrowed_token.approve(self.amm.address, 2**256 - 1)

            amount_too_low = deposit_amount_too_low(
                self.amm, amount, n1, n2, self.collateral_mul
            )
            try:
                with boa.env.prank(self.admin):
                    self.amm.deposit_range(user, amount, n1, n2)
                    mint_for_testing(self.collateral_token, self.amm.address, amount)
            except Exception as e:
                if "Amount too low" in str(e):
                    assert amount_too_low
                else:
                    raise
        self.deposited = [self.amm.bands_y(n) for n in range(42)]
        self.total_deposited = sum(self.deposited)
        self.initial_price = self.amm.price_oracle()
        # Nothing is sold before p_oracle reaches the bands
        assert self.amm.get_dydx(0, 1, 10**30) == (0, 0)
        # p_oracle falls to the deepest deposited band or only half way to it
        self.n_o = self.amm.max_band()
        if part:
            self.n_o //= 2
        with boa.env.prank(self.admin):
            self.price_oracle.set_price(self.amm.p_oracle_down(self.n_o))
        boa.env.time_travel(600)  # To reset the prev p_o counter

    @rule(amount=amount, pump=pump, user_id=user_id)
    def exchange(self, amount, pump, user_id):
        amount = int(amount * 10**self.collateral_digits)
        u = self.users[user_id]
        if pump:
            i = 0
            j = 1
            in_token = self.borrowed_token
        else:
            i = 1
            j = 0
            in_token = self.collateral_token
        u_amount = in_token.balanceOf(u)
        if not pump:
            # Collateral is never bought back
            with boa.reverts("Wrong index"):
                self.amm.get_dydx(i, j, amount)
            with boa.env.prank(u):
                with boa.reverts("Wrong index"):
                    self.amm.exchange_dy(i, j, amount, 2**256 - 1)
            return
        reduced_amount, required_amount = self.amm.get_dydx(i, j, amount)
        if required_amount > u_amount:
            mint_for_testing(in_token, u, required_amount - u_amount)
        with boa.env.prank(u):
            self.amm.exchange_dy(i, j, reduced_amount, required_amount)

    @invariant()
    def amm_solvent(self):
        X = sum(self.amm.bands_x(n) for n in range(42))
        Y = sum(self.amm.bands_y(n) for n in range(42))
        assert self.borrowed_token.balanceOf(self.amm) * self.borrowed_mul >= X
        assert self.collateral_token.balanceOf(self.amm) * self.collateral_mul >= Y

    @invariant()
    def dy_back(self):
        to_receive = (
            self.total_deposited
            * self.initial_price
            * 10
            // 10**18
            // self.borrowed_mul
        )  # Huge amount
        # Sold collateral is never bought back
        with boa.reverts("Wrong index"):
            self.amm.get_dydx(1, 0, to_receive)
        with boa.reverts("Wrong index"):
            self.amm.get_dx(1, 0, to_receive)
        to_receive = self.total_deposited // 1000 // self.collateral_mul  # Small amount
        dy, dx = self.amm.get_dydx(0, 1, to_receive)
        if dy == to_receive:
            assert dx == self.amm.get_dx(0, 1, to_receive)
            # Price only goes up, and the fee is paid on top
            assert (
                dx * self.borrowed_mul * (10**18 - self.amm.fee())
                >= dy * self.collateral_mul * self.amm.get_p()
            )
        else:
            with boa.reverts():
                self.amm.get_dx(0, 1, to_receive)
        for n in range(42):
            sold = self.deposited[n] - self.amm.bands_y(n)
            p_down = self.amm.p_current_down(n)
            assert (
                self.amm.bands_x(n) * (10**18 - self.amm.fee()) >= sold * p_down
            )  # With fees, AMM will have more
            if n > self.amm.active_band():
                assert self.amm.bands_x(n) == 0
            if n > self.n_o + 1:
                # Collateral is sold only from bands which p_oracle has reached
                assert sold == 0

    def teardown(self):
        u = self.users[0]
        # Nothing is traded back
        to_receive = (
            self.total_deposited
            * self.initial_price
            * 10
            // 10**18
            // self.borrowed_mul
        )  # Huge amount
        with boa.env.prank(u):
            with boa.reverts("Wrong index"):
                self.amm.exchange_dy(1, 0, to_receive, 2**256 - 1)


@pytest.mark.parametrize("borrowed_digits", [6, 8, 18])
@pytest.mark.parametrize("collateral_digits", [6, 8, 18])
def test_exchange(admin, price_oracle, get_amm, borrowed_digits, collateral_digits):
    StatefulExchange.TestCase.settings = settings(
        max_examples=20,
        stateful_step_count=10,
        phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target),
        suppress_health_check=[HealthCheck.data_too_large],
    )
    users = [boa.env.generate_address() for _ in range(5)]

    borrowed_token = ERC20_MOCK_DEPLOYER.deploy(borrowed_digits)
    collateral_token = ERC20_MOCK_DEPLOYER.deploy(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)
    run_state_machine_as_test(StatefulExchange)


def test_raise_at_dy_back(admin, price_oracle, get_amm):
    StatefulExchange.TestCase.settings = settings(
        max_examples=200,
        stateful_step_count=10,
        phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target),
    )
    users = [boa.env.generate_address() for _ in range(5)]

    borrowed_digits = 18
    collateral_digits = 18
    borrowed_token = ERC20_MOCK_DEPLOYER.deploy(borrowed_digits)
    collateral_token = ERC20_MOCK_DEPLOYER.deploy(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)

    state = StatefulExchange()
    state.initializer(
        amounts=[0.0, 0.0, 0.0, 1.0, 1.0], ns=[1, 1, 1, 1, 2], dns=[0, 0, 0, 0, 0]
    )
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=1.0, pump=True, user_id=0)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=1.0, pump=True, user_id=0)
    state.amm_solvent()
    state.dy_back()
    state.teardown()


def test_raise_not_enough_left(admin, price_oracle, get_amm):
    StatefulExchange.TestCase.settings = settings(
        max_examples=200,
        stateful_step_count=10,
        phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target),
    )
    users = [boa.env.generate_address() for _ in range(5)]

    borrowed_digits = 16
    collateral_digits = 13
    borrowed_token = ERC20_MOCK_DEPLOYER.deploy(borrowed_digits)
    collateral_token = ERC20_MOCK_DEPLOYER.deploy(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)

    state = StatefulExchange()
    state.initializer(
        amounts=[
            419403.0765402276,
            1.0,
            5e-324,
            5.960464477539063e-08,
            999999.9999999999,
        ],
        ns=[17, 16, 14, 14, 16],
        dns=[15, 7, 2, 11, 16],
    )
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=6.103515625e-05, pump=True, user_id=2)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=14177506.010146782, pump=True, user_id=0)
    state.amm_solvent()
    state.dy_back()
    state.teardown()
