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

    @initialize(amounts=amounts, ns=ns, dns=dns)
    def initializer(self, amounts, ns, dns):
        self.borrowed_mul = 10 ** (18 - self.borrowed_digits)
        self.collateral_mul = 10 ** (18 - self.collateral_digits)
        amounts = list(map(lambda x: int(x * 10**self.collateral_digits), amounts))
        for user, amount, n1, dn in zip(self.accounts, amounts, ns, dns):
            n2 = n1 + dn
            try:
                with boa.env.prank(self.admin):
                    self.amm.deposit_range(user, amount, n1, n2)
                    mint_for_testing(self.collateral_token, self.amm.address, amount)
            except Exception as e:
                if "Amount too low" in str(e):
                    assert amount // (dn + 1) <= 100
                else:
                    raise
        self.total_deposited = sum(self.amm.bands_y(n) for n in range(42))
        self.initial_price = self.amm.price_oracle()

    @rule(amount=amount, pump=pump, user_id=user_id)
    def exchange(self, amount, pump, user_id):
        amount = int(amount * 10**self.collateral_digits)
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
        n = self.amm.active_band()
        to_receive = (
            self.total_deposited
            * self.initial_price
            * 10
            // 10**18
            // self.borrowed_mul
        )  # Huge amount
        left_in_amm = sum(self.amm.bands_y(n) for n in range(42))
        if n < 50:
            dy, dx = self.amm.get_dydx(1, 0, to_receive)
            if dy == to_receive:
                dx = self.amm.get_dx(1, 0, to_receive)
            else:
                with boa.reverts():
                    self.amm.get_dx(1, 0, to_receive)
            assert (
                dx * self.collateral_mul >= self.total_deposited - left_in_amm
            )  # With fees, AMM will have more

    def teardown(self):
        u = self.accounts[0]
        # Trade back and do the check
        n = self.amm.active_band()
        to_receive = (
            self.total_deposited
            * self.initial_price
            * 10
            // 10**18
            // self.borrowed_mul
        )  # Huge amount
        if n < 50:
            dy, dx = self.amm.get_dydx(1, 0, to_receive)
            if dy > 0:
                mint_for_testing(self.collateral_token, u, dx)
                with boa.env.prank(u):
                    self.amm.exchange_dy(1, 0, 2**256 - 1, dx)
                left_in_amm = sum(self.amm.bands_y(n) for n in range(42))
                assert left_in_amm >= self.total_deposited


@pytest.mark.parametrize("borrowed_digits", [6, 8, 18])
@pytest.mark.parametrize("collateral_digits", [6, 8, 18])
def test_exchange(admin, accounts, get_amm, borrowed_digits, collateral_digits):
    StatefulExchange.TestCase.settings = settings(
        max_examples=20,
        stateful_step_count=10,
        phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target),
        suppress_health_check=[HealthCheck.data_too_large],
    )
    accounts = accounts[:5]

    borrowed_token = ERC20_MOCK_DEPLOYER.deploy(borrowed_digits)
    collateral_token = ERC20_MOCK_DEPLOYER.deploy(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)
    run_state_machine_as_test(StatefulExchange)


def test_raise_at_dy_back(admin, accounts, get_amm):
    StatefulExchange.TestCase.settings = settings(
        max_examples=200,
        stateful_step_count=10,
        phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target),
    )
    accounts = accounts[:5]

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


def test_raise_not_enough_left(admin, accounts, get_amm):
    StatefulExchange.TestCase.settings = settings(
        max_examples=200,
        stateful_step_count=10,
        phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target),
    )
    accounts = accounts[:5]

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
