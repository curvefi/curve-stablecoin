import boa
import pytest
from hypothesis import strategies as st, given
from tests.utils.deployers import MOCK_PEG_KEEPER_DEPLOYER

ADMIN_ACTIONS_DEADLINE = 3 * 86400


def test_aggregator_price(peg_keepers, mock_peg_keepers, reg, agg, admin, stablecoin):
    mock_peg_keeper = MOCK_PEG_KEEPER_DEPLOYER.deploy(10**18, stablecoin)
    for peg_keeper in peg_keepers:
        stablecoin.eval(f"self.balanceOf[{peg_keeper.address}] += {10**18}")
    with boa.env.prank(admin):
        agg.add_price_pair(mock_peg_keeper)
        for price in [0.95, 1.05]:
            mock_peg_keeper.set_price(int(price * 10**18))
            boa.env.time_travel(seconds=50000)
            for peg_keeper in peg_keepers:
                assert (reg.provide_allowed(peg_keeper) > 0) == (price > 1)
                assert (reg.withdraw_allowed(peg_keeper) > 0) == (price < 1)


def test_delta_limit(peg_keepers, mock_peg_keepers, reg, admin, stablecoin):
    all_pks = mock_peg_keepers + peg_keepers
    for pk in all_pks:
        pk.eval("self.debt = 0")
    debt_share, ceiling_share = reg.debt_delta_share(), reg.ceiling_delta_share()
    pk = peg_keepers[-1]
    pk.eval("self.debt = 10 ** 18")
    stablecoin.eval(f"self.balanceOf[{pk.address}] = {3 * 10**18}")
    ceiling = pk.debt() + pk.undrawn()
    total_debt = sum(p.debt() for p in all_pks)
    limit = max(debt_share * total_debt, ceiling_share * ceiling) // 10**18
    assert limit == ceiling_share * ceiling // 10**18  # own ceiling floor binds with little debt

    # nothing provided in the window: the whole limit is allowed
    pk.eval("self.recorded_delta = 0")
    assert reg.provide_allowed(pk.address) == limit

    # provided in the window is subtracted, withdrawn is credited
    for delta in (limit // 3, limit, 2 * limit, -limit):
        pk.eval(f"self.recorded_delta = {delta}")
        pk.eval("self.last_change = block.timestamp")
        assert reg.provide_allowed(pk.address) == max(0, limit - delta)

    # forgotten linearly over the delta window
    pk.eval(f"self.recorded_delta = {limit}")
    pk.eval("self.last_change = block.timestamp")
    boa.env.time_travel(seconds=pk.delta_window() // 2)
    assert reg.provide_allowed(pk.address) == pytest.approx(limit // 2, abs=1)
    boa.env.time_travel(seconds=pk.delta_window())
    assert reg.provide_allowed(pk.address) == limit

    # total debt of all keepers lifts the limit above the own ceiling floor
    for mock in mock_peg_keepers:
        mock.set_debt(50 * 10**18)
    total_debt = sum(p.debt() for p in all_pks)
    assert reg.provide_allowed(pk.address) == debt_share * total_debt // 10**18
    for mock in mock_peg_keepers:
        mock.set_debt(0)

    # shares 0 ban provide, ceiling share 1 allows the whole ceiling
    with boa.env.prank(admin):
        reg.set_delta_shares(0, 0)
        assert reg.provide_allowed(pk.address) == 0
        reg.set_delta_shares(0, 10**18)
        assert reg.provide_allowed(pk.address) == ceiling
        reg.set_delta_shares(debt_share, ceiling_share)


def test_set_killed(reg, peg_keepers, admin, stablecoin):
    peg_keeper = peg_keepers[0]
    stablecoin.eval(f"self.balanceOf[{peg_keeper.address}] += {10**18}")
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


def test_admin(reg, admin, alice, agg, receiver):
    # initial parameters
    assert (reg.debt_delta_share(), reg.ceiling_delta_share()) == (10**18 // 10, 10**18 // 20)
    assert reg.aggregator() == agg.address
    assert reg.fee_receiver() == receiver
    assert reg.emergency_admin() == admin
    assert reg.is_killed() == 0
    assert reg.admin() == admin

    # third party has no access
    with boa.env.prank(alice):
        with boa.reverts():
            reg.set_delta_shares(10**18 // 5, 10**18 // 5)
        with boa.reverts():
            reg.set_aggregator(alice)
        with boa.reverts():
            reg.set_fee_receiver(alice)
        with boa.reverts():
            reg.set_emergency_admin(alice)
        with boa.reverts():
            reg.set_killed(1)
        with boa.reverts():
            reg.set_admin(alice)

    # admin has access
    with boa.env.prank(admin):
        reg.set_delta_shares(10**18 // 5, 10**18 // 10)
        assert (reg.debt_delta_share(), reg.ceiling_delta_share()) == (10**18 // 5, 10**18 // 10)
        with boa.reverts():
            reg.set_delta_shares(10**18 + 1, 0)
        with boa.reverts():
            reg.set_delta_shares(0, 10**18 + 1)

        reg.set_aggregator(alice)
        assert reg.aggregator() == alice

        reg.set_fee_receiver(alice)
        assert reg.fee_receiver() == alice

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
        reg.peg_keepers(i)[0]
        for i in range(reg.eval("len(self.peg_keepers)", return_type="uint256"))
    ]


@pytest.fixture(scope="module")
def preset_peg_keepers(reg, admin, stablecoin):
    with boa.env.prank(admin):
        reg.remove_peg_keepers(get_peg_keepers(reg))
    return [
        MOCK_PEG_KEEPER_DEPLOYER.deploy((1 + i) * 10**18, stablecoin).address
        for i in range(8)
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
    js=st.lists(
        st.integers(min_value=0, max_value=7), min_size=1, max_size=8, unique=True
    ),
)
def test_remove_peg_keepers(reg, admin, preset_peg_keepers, i, js):
    i = max(i, max(js) + 1)
    with boa.env.prank(admin):
        reg.add_peg_keepers(preset_peg_keepers[:i])
        assert get_peg_keepers(reg) == preset_peg_keepers[:i]

        to_remove = [preset_peg_keepers[j] for j in js]
        reg.remove_peg_keepers(to_remove)
        assert set(get_peg_keepers(reg)) == set(
            [preset_peg_keepers[k] for k in range(i) if k not in js]
        )


def test_peg_keepers_bad_values(reg, admin, preset_peg_keepers):
    with boa.env.prank(admin):
        reg.add_peg_keepers(preset_peg_keepers)

        with boa.reverts():  # Too many values
            reg.add_peg_keepers(preset_peg_keepers[:1])

        reg.remove_peg_keepers(preset_peg_keepers[:2])
        with boa.reverts():  # Could not find
            reg.remove_peg_keepers(preset_peg_keepers[1:3])
        with boa.reverts():  # Duplicate
            reg.add_peg_keepers(preset_peg_keepers[1:3])
        with boa.reverts():  # Duplicate
            reg.add_peg_keepers([preset_peg_keepers[0]] * 2)
