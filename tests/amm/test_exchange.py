import boa
from ..conftest import approx
from hypothesis import given, settings
from hypothesis import strategies as st
from datetime import timedelta

from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, rule, initialize


@given(
        amounts=st.lists(st.integers(min_value=10**16, max_value=10**6 * 10**18), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
)
@settings(deadline=timedelta(seconds=1000))
def test_dxdy_limits(amm, amounts, accounts, ns, dns, collateral_token, admin):
    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            amm.deposit_range(user, amount, n1, n2)
            collateral_token._mint_for_testing(amm.address, amount)

    # Swap 0
    dx, dy = amm.get_dxdy(0, 1, 0)
    assert dx == 0 and dy == 0
    dx, dy = amm.get_dxdy(1, 0, 0)
    assert dx == dy == 0

    # Small swap
    dx, dy = amm.get_dxdy(0, 1, 10**2)  # $0.0001
    assert dx == 10**2
    assert approx(dy, dx * 10**(18 - 6) / 3000, 4e-2 + 2 * min(ns) / amm.A())
    dx, dy = amm.get_dxdy(1, 0, 10**16)  # No liquidity
    assert dx == 0
    assert dy == 0  # Rounded down

    # Huge swap
    dx, dy = amm.get_dxdy(0, 1, 10**12 * 10**6)
    assert dx < 10**12 * 10**6               # Less than all is spent
    assert abs(dy - sum(amounts)) <= 1000    # but everything is bought
    dx, dy = amm.get_dxdy(1, 0, 10**12 * 10**18)
    assert dx == 0
    assert dy == 0  # Rounded down


@given(
        amounts=st.lists(st.integers(min_value=10**16, max_value=10**6 * 10**18), min_size=5, max_size=5),
        ns=st.lists(st.integers(min_value=1, max_value=20), min_size=5, max_size=5),
        dns=st.lists(st.integers(min_value=0, max_value=20), min_size=5, max_size=5),
        amount=st.integers(min_value=0, max_value=10**9 * 10**6)
)
@settings(deadline=timedelta(seconds=1000))
def test_exchange_down_up(amm, amounts, accounts, ns, dns, amount,
                          borrowed_token, collateral_token, admin):
    u = accounts[6]

    with boa.env.prank(admin):
        for user, amount, n1, dn in zip(accounts[1:6], amounts, ns, dns):
            n2 = n1 + dn
            if amount // (dn + 1) <= 100:
                with boa.reverts("Amount too low"):
                    amm.deposit_range(user, amount, n1, n2)
            else:
                amm.deposit_range(user, amount, n1, n2)
                collateral_token._mint_for_testing(amm.address, amount)

    dx, dy = amm.get_dxdy(0, 1, amount)
    assert dx <= amount
    dx2, dy2 = amm.get_dxdy(0, 1, dx)
    assert dx == dx2
    assert approx(dy, dy2, 1e-6)
    borrowed_token._mint_for_testing(u, dx2)
    with boa.env.prank(u):
        amm.exchange(0, 1, dx2, 0)
    assert borrowed_token.balanceOf(u) == 0
    assert collateral_token.balanceOf(u) == dy2

    sum_borrowed = sum(amm.bands_x(i) for i in range(50))
    sum_collateral = sum(amm.bands_y(i) for i in range(50))
    assert abs(borrowed_token.balanceOf(amm) - sum_borrowed // 10**(18 - 6)) <= 1
    assert abs(collateral_token.balanceOf(amm) - sum_collateral) <= 1

    in_amount = int(dy2 / 0.98)  # two trades charge 1% twice
    expected_out_amount = dx2

    dx, dy = amm.get_dxdy(1, 0, in_amount)
    assert approx(dx, in_amount, 5e-4)  # Not precise because fee is charged on different directions
    assert abs(dy - expected_out_amount) <= 1

    collateral_token._mint_for_testing(u, dx - collateral_token.balanceOf(u))
    dy_measured = borrowed_token.balanceOf(u)
    dx_measured = collateral_token.balanceOf(u)
    with boa.env.prank(u):
        amm.exchange(1, 0, in_amount, 0)
    dy_measured = borrowed_token.balanceOf(u) - dy_measured
    dx_measured -= collateral_token.balanceOf(u)
    assert dy == dy_measured
    assert dx == dx_measured


class NoUntradableFunds(RuleBasedStateMachine):
    n1 = st.integers(min_value=1, max_value=40)
    dn = st.integers(min_value=0, max_value=20)
    amount_in = st.integers(min_value=1, max_value=10**18)
    decimals_borrowed = st.integers(min_value=6, max_value=18)
    decimals_collateral = st.integers(min_value=6, max_value=18)

    def __init__(self):
        super().__init__()
        self.user = self.accounts[1]

    @initialize(decimals_borrowed=decimals_borrowed, decimals_collateral=decimals_collateral)
    def initializer(self, decimals_borrowed, decimals_collateral):
        self.decimals_borrowed = decimals_borrowed
        self.decimals_collateral = decimals_collateral
        # These are slow operations
        self.borrowed_token = NoUntradableFunds.get_borrowed_token(decimals_borrowed)
        self.collateral_token = NoUntradableFunds.get_collateral_token(decimals_collateral)
        self.amm = NoUntradableFunds.get_amm(self.collateral_token, self.borrowed_token)

    @rule(n1=n1, dn=dn, amount_in=amount_in)
    def trade_up_down(self, n1, dn, amount_in):
        collateral_a = 10 ** self.decimals_collateral
        to_swap = amount_in // 10 ** (18 - self.decimals_borrowed)

        with boa.env.anchor():
            # Deposit
            with boa.env.prank(self.admin):
                self.amm.deposit_range(self.user, collateral_a, n1, n1 + dn)
                self.collateral_token._mint_for_testing(self.amm.address, collateral_a)

            # Swap stablecoin for collateral
            self.borrowed_token._mint_for_testing(self.user, to_swap)
            with boa.env.prank(self.user):
                self.amm.exchange(0, 1, to_swap, 0)
            b = self.borrowed_token.balanceOf(self.user)
            if b < to_swap:
                collateral_amount = self.collateral_token.balanceOf(self.user)
                assert collateral_amount != 0
            else:
                return  # No real swap

            # Swap a lot back
            self.collateral_token._mint_for_testing(self.user, 10 ** self.decimals_collateral)  # BIG
            with boa.env.prank(self.user):
                self.amm.exchange(1, 0, 10 ** self.decimals_collateral, 0)
            # Check that we cleaned up the last band
            assert self.amm.bands_x(n1) == 0
            assert self.borrowed_token.balanceOf(self.user) > b


def test_no_untradable_funds(accounts, admin, get_borrowed_token, get_collateral_token, get_amm):
    NoUntradableFunds.TestCase.settings = settings(max_examples=20, stateful_step_count=500,
                                                   deadline=timedelta(seconds=1000))
    for k, v in locals().items():
        setattr(NoUntradableFunds, k, v)
    run_state_machine_as_test(NoUntradableFunds)
