import boa
import pytest
from hypothesis import strategies as st
from hypothesis import given


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ADMIN_ACTIONS_DEADLINE = 3 * 86400


def test_price_range(peg_keepers, swaps, stablecoin, admin, receiver, reg):
    with boa.env.prank(admin):
        reg.set_price_deviation(10 ** 17)
        for peg_keeper in peg_keepers:
            stablecoin.eval(f"self.balanceOf[{peg_keeper.address}] += {10 ** 18}")

    for peg_keeper, swap in zip(peg_keepers, swaps):
        assert reg.provide_allowed(peg_keeper)
        assert reg.withdraw_allowed(peg_keeper)

        # Move current price (get_p) a little
        swap.eval("self.rate_multipliers[0] *= 2")
        assert reg.provide_allowed(peg_keeper)
        assert reg.withdraw_allowed(peg_keeper)

        # Move further
        swap.eval("self.rate_multipliers[0] *= 5")

        assert not reg.provide_allowed(peg_keeper)
        assert not reg.withdraw_allowed(peg_keeper)


def test_price_order(peg_keepers, mock_peg_keepers, swaps, initial_amounts, stablecoin, admin, alice, mint_alice, reg, agg):
    with boa.env.prank(admin):
        reg.remove_peg_keepers([mock.address for mock in mock_peg_keepers])

    # note: assuming swaps' prices are close enough
    for i, (peg_keeper, swap, (initial_amount, _)) in enumerate(zip(peg_keepers, swaps, initial_amounts)):
        with boa.env.anchor():
            with boa.env.prank(admin):
                # Price change break aggregator.price() check
                agg.remove_price_pair(i)

            with boa.env.prank(alice):
                amount = 7 * initial_amount // 1000  # Just in
                # Make sure small decline still works
                swap.exchange(0, 1, amount, 0)
                boa.env.time_travel(seconds=6000)  # Update EMA
                assert reg.provide_allowed(peg_keeper)
                assert reg.withdraw_allowed(peg_keeper)  # no such check for withdraw

                # and a bigger one
                swap.exchange(0, 1, amount, 0)
                boa.env.time_travel(seconds=6000)  # Update EMA
                assert not reg.provide_allowed(peg_keeper)
                assert reg.withdraw_allowed(peg_keeper)


def test_aggregator_price(peg_keepers, mock_peg_keepers, reg, agg, admin, stablecoin):
    mock_peg_keeper = boa.load('contracts/testing/MockPegKeeper.vy', 10 ** 18, stablecoin)
    with boa.env.prank(admin):
        agg.add_price_pair(mock_peg_keeper)
        for price in [0.95, 1.05]:
            mock_peg_keeper.set_price(int(price * 10 ** 18))
            boa.env.time_travel(seconds=50000)
            for peg_keeper in peg_keepers:
                assert (reg.provide_allowed(peg_keeper) > 0) == (price > 1)
                assert (reg.withdraw_allowed(peg_keeper) > 0) == (price < 1)


def test_set_killed(reg, peg_keepers, admin):
    peg_keeper = peg_keepers[0]
    with boa.env.prank(admin):
        assert reg.is_killed() == 0

        assert reg.provide_allowed(peg_keeper)
        assert reg.withdraw_allowed(peg_keeper)

        reg.set_killed(1)
        assert reg.is_killed() == 1

        assert not reg.provide_allowed(peg_keeper)
        assert reg.withdraw_allowed(peg_keeper)

        reg.set_killed(2)
        assert reg.is_killed() == 2

        assert reg.provide_allowed(peg_keeper)
        assert not reg.withdraw_allowed(peg_keeper)

        reg.set_killed(3)
        assert reg.is_killed() == 3

        assert not reg.provide_allowed(peg_keeper)
        assert not reg.withdraw_allowed(peg_keeper)


def test_admin(reg, admin, alice):
    # initial parameters
    assert reg.price_deviation() == 100 * 10 ** 18
    assert (reg.alpha(), reg.beta()) == (10 ** 18, 10 ** 18)
    assert reg.emergency_admin() == admin
    assert reg.is_killed() == 0
    assert reg.admin() == admin

    # third party has no access
    with boa.env.prank(alice):
        with boa.reverts():
            reg.set_price_deviation(10 ** 17)
        with boa.reverts():
            reg.set_debt_parameters(10 ** 18 // 2, 10 ** 18 // 5)
        with boa.reverts():
            reg.set_emergency_admin(alice)
        with boa.reverts():
            reg.set_killed(1)
        with boa.reverts():
            reg.set_admin(alice)

    # admin has access
    with boa.env.prank(admin):
        reg.set_price_deviation(10 ** 17)
        assert reg.price_deviation() == 10 ** 17

        reg.set_debt_parameters(10 ** 18 // 2, 10 ** 18 // 5)
        assert (reg.alpha(), reg.beta()) == (10 ** 18 // 2, 10 ** 18 // 5)

        reg.set_emergency_admin(alice)
        assert reg.emergency_admin() == alice

        reg.set_killed(1)
        assert reg.is_killed() == 1
        with boa.env.prank(alice):  # emergency admin
            reg.set_killed(2)
            assert reg.is_killed() == 2

        reg.set_admin(alice)
        assert reg.admin() == alice


def get_peg_keepers(reg):
    return [
        # pk.get("peg_keeper") for pk in reg._storage.peg_keepers.get()  Available for titanoboa >= 0.1.8
        reg.peg_keepers(i)[0] for i in range(reg.eval("len(self.peg_keepers)"))
    ]


@pytest.fixture(scope="module")
def preset_peg_keepers(reg, admin, stablecoin):
    with boa.env.prank(admin):
        reg.remove_peg_keepers(get_peg_keepers(reg))
    return [
        boa.load('contracts/testing/MockPegKeeper.vy', (1 + i) * 10 ** 18, stablecoin).address for i in range(8)
    ]


@given(
    i=st.integers(min_value=1, max_value=8),
    j=st.integers(min_value=1, max_value=7),
)
def test_add_peg_keepers(reg, admin, preset_peg_keepers, i, j):
    j = min(i + j, 8)
    with boa.env.prank(admin):
        reg.add_peg_keepers(preset_peg_keepers[:i])
        assert get_peg_keepers(reg) == preset_peg_keepers[:i]
        if j > i:
            reg.add_peg_keepers(preset_peg_keepers[i:j])
            assert get_peg_keepers(reg) == preset_peg_keepers[:j]


@given(
    i=st.integers(min_value=1, max_value=8),
    js=st.lists(st.integers(min_value=0, max_value=7), min_size=1, max_size=8, unique=True),
)
def test_remove_peg_keepers(reg, admin, preset_peg_keepers, i, js):
    i = max(i, max(js) + 1)
    with boa.env.prank(admin):
        reg.add_peg_keepers(preset_peg_keepers[:i])
        assert get_peg_keepers(reg) == preset_peg_keepers[:i]

        to_remove = [preset_peg_keepers[j] for j in js]
        reg.remove_peg_keepers(to_remove)
        assert set(get_peg_keepers(reg)) == set([preset_peg_keepers[k] for k in range(i) if k not in js])


def test_peg_keepers_bad_values(reg, admin, preset_peg_keepers):
    with boa.env.prank(admin):
        reg.add_peg_keepers(preset_peg_keepers)

        with boa.reverts():  # Too many values
            reg.add_peg_keepers(preset_peg_keepers[:1])

        reg.remove_peg_keepers(preset_peg_keepers[:1])
        with boa.reverts():  # Could not find
            reg.remove_peg_keepers(preset_peg_keepers[:1])
