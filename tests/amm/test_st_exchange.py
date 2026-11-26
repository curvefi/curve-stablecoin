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
    amounts = st.lists(
        st.integers(min_value=0, max_value=10**6 * 10**18), min_size=5, max_size=5
    )
    ns = st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5)
    dns = st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5)
    amount = st.integers(min_value=0, max_value=10**9 * 10**18)
    pump = st.booleans()
    user_id = st.integers(min_value=0, max_value=4)

    def __init__(self):
        super().__init__()
        self.total_deposited = 0

    @initialize(amounts=amounts, ns=ns, dns=dns, part=pump)
    def initializer(self, amounts, ns, dns, part=False):
        self.borrowed_mul = 10 ** (18 - self.borrowed_digits)
        self.collateral_mul = 10 ** (18 - self.collateral_digits)
        amounts = [a // self.collateral_mul for a in amounts]
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
        # Nothing is sold before p_oracle reaches the bands
        assert self.amm.get_dxdy(0, 1, 10**30) == (0, 0)
        # p_oracle falls to the deepest deposited band or only half way to it
        self.n_o = self.amm.max_band()
        if part:
            self.n_o //= 2
        with boa.env.prank(self.admin):
            self.price_oracle.set_price(self.amm.p_oracle_down(self.n_o))
        boa.env.time_travel(600)  # To reset the prev p_o counter

    @rule(amount=amount, pump=pump, user_id=user_id)
    def exchange(self, amount, pump, user_id):
        u = self.users[user_id]
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
            mint_for_testing(in_token, u, amount - u_amount)
        with boa.env.prank(u):
            if pump:
                self.amm.exchange(i, j, amount, 0)
            else:
                # Collateral is never bought back
                with boa.reverts("Wrong index"):
                    self.amm.exchange(i, j, amount, 0)

    @invariant()
    def amm_solvent(self):
        X = sum(self.amm.bands_x(n) for n in range(42))
        Y = sum(self.amm.bands_y(n) for n in range(42))
        assert self.borrowed_token.balanceOf(self.amm) * self.borrowed_mul >= X
        assert self.collateral_token.balanceOf(self.amm) * self.collateral_mul >= Y

    @invariant()
    def dy_back(self):
        to_swap = self.total_deposited * 10 // self.collateral_mul
        # Sold collateral is never bought back
        with boa.reverts("Wrong index"):
            self.amm.get_dxdy(1, 0, to_swap)
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
        if not hasattr(self, "amm"):
            return
        u = self.users[0]
        # Nothing is traded back
        to_swap = self.total_deposited * 10 // self.collateral_mul
        mint_for_testing(self.collateral_token, u, to_swap)
        with boa.env.prank(u):
            with boa.reverts("Wrong index"):
                self.amm.exchange(1, 0, to_swap, 0)


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
        amounts=[0, 0, 0, 10**18, 10**18], ns=[1, 1, 1, 1, 2], dns=[0, 0, 0, 0, 0]
    )
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=3123061067055650168655, pump=True, user_id=0)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=3123061067055650168655, pump=True, user_id=0)
    state.amm_solvent()
    state.dy_back()
    state.teardown()


def test_raise_rounding(admin, price_oracle, get_amm):
    users = [boa.env.generate_address() for _ in range(5)]

    borrowed_digits = 16
    collateral_digits = 18

    borrowed_token = ERC20_MOCK_DEPLOYER.deploy(borrowed_digits)
    collateral_token = ERC20_MOCK_DEPLOYER.deploy(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)
    state = StatefulExchange()
    state.initializer(
        amounts=[101, 0, 0, 0, 0], ns=[1, 1, 1, 1, 1], dns=[0, 0, 0, 0, 0]
    )
    state.exchange(amount=100, pump=True, user_id=0)
    state.dy_back()
    state.teardown()


def test_raise_rounding_2(admin, price_oracle, get_amm):
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
        amounts=[779, 5642, 768, 51924, 5],
        ns=[2, 3, 4, 10, 18],
        dns=[11, 12, 14, 15, 15],
    )
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=42, pump=True, user_id=1)
    state.amm_solvent()
    state.dy_back()
    state.exchange(amount=512, pump=True, user_id=2)
    state.amm_solvent()
    state.dy_back()
    state.teardown()


def test_raise_rounding_3(admin, price_oracle, get_amm):
    users = [boa.env.generate_address() for _ in range(5)]

    borrowed_digits = 17
    collateral_digits = 18

    borrowed_token = ERC20_MOCK_DEPLOYER.deploy(borrowed_digits)
    collateral_token = ERC20_MOCK_DEPLOYER.deploy(collateral_digits)
    amm = get_amm(collateral_token, borrowed_token)

    for k, v in locals().items():
        setattr(StatefulExchange, k, v)
    state = StatefulExchange()
    state.initializer(
        amounts=[33477, 63887, 387, 1, 0], ns=[4, 18, 6, 19, 5], dns=[18, 0, 8, 20, 5]
    )
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
