import boa
import pytest
from collections import defaultdict

RATE0 = 634195839  # 2%
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


@pytest.fixture(scope="module")
def mock_factory(admin):
    with boa.env.prank(admin):
        factory = boa.load('contracts/testing/MockFactory.vy')
        for i in range(3):
            market = boa.load('contracts/testing/MockMarket.vy')
            factory.add_market(market.address, 10**6 * 10**18)
    return factory


@pytest.fixture(scope="module")
def mock_peg_keepers(admin):
    with boa.env.prank(admin):
        pks = []
        for i in range(4):
            pk = boa.load('contracts/testing/MockPegKeeper.vy')
            pk.set_debt(10**4 * 10**18)
            pks.append(pk)
        return pks


@pytest.fixture(scope='module')
def mp(mock_factory, mock_peg_keepers, price_oracle, admin):
    with boa.env.prank(admin):
        price_oracle.set_price(10**18)

        return boa.load(
            'contracts/mpolicies/AggMonetaryPolicy3.vy',
            admin,
            price_oracle.address,
            mock_factory.address,
            [p.address for p in mock_peg_keepers] + [ZERO_ADDRESS],
            RATE0,
            2 * 10**16,  # Sigma 2%
            5 * 10**16)  # Target debt fraction 5%


def test_broken_markets(mp, mock_factory, admin):
    with boa.env.prank(admin):
        # Set debts
        for i in range(3):
            controller = mock_factory.controllers(i)
            mock_factory.set_debt(controller, (i + 1) * 10**5 * 10**18)
            assert mock_factory.debt_ceiling(controller) == 10**6 * 10**18
        assert mock_factory.total_debt() == 6 * 10**5 * 10**18
        mp.rate_write()  # Saving cache of controllers
        rate = mp.rate()
        assert rate > 0

        # Add broken controller - it is an EOA, so all calls will revert
        mock_factory.add_market(admin, 10**6)
        with boa.reverts():
            mock_factory.total_debt()
        assert rate == mp.rate()
        mp.rate_write()  # Saving cache of controllers
        assert rate == mp.rate()


def test_candles(mp, mock_factory, admin):
    with boa.env.prank(admin):
        points_per_day = 25
        MAX_RATE = 43959106799

        mp.rate_write()  # Saving cache of controllers - they never change in this test afterwards
        controllers = [mock_factory.controllers(i) for i in range(3)]
        max_diff_for = defaultdict(int)
        rates = {c: mp.rate(c) for c in controllers}

        for t in range(1, 500):
            controller = controllers[t % 3]
            new_debt = t * 10**5 * 10**18
            mock_factory.set_debt(controller, new_debt)
            d_total_0, d_for_0 = mp.internal.read_debt(controller, True)
            mp.rate_write(controller)
            d_total_1, d_for_1 = mp.internal.read_debt(controller, False)
            current_total = mock_factory.total_debt()
            assert d_total_0 == d_total_1 <= current_total
            assert d_for_0 == d_for_1
            max_diff_for[controller] = max(max_diff_for[controller], new_debt - d_for_1)

            new_rate = mp.rate(controller)
            assert new_rate >= rates[controller]
            assert new_rate > 0
            assert new_rate <= MAX_RATE
            rates[controller] = new_rate

            boa.env.time_travel(86400 // points_per_day)

        for c in controllers:
            assert max_diff_for[c] > 0
            assert max_diff_for[c] < (points_per_day * 10**5 * 10**18)
            assert rates[c] == MAX_RATE


def test_add_controllers(mp, mock_factory, admin):
    additional_debts = [10**6, 3 * 10**6, 5 * 10**6]
    additional_ceilings = [10**7, 10**8, 10**9]
    added_debt = 0

    initial_debt, _ = mp.internal.get_total_debt(ZERO_ADDRESS)

    with boa.env.prank(admin):
        for ceiling, debt in zip(additional_ceilings, additional_debts):
            market = boa.load('contracts/testing/MockMarket.vy')
            mock_factory.add_market(market.address, ceiling)
            mp.rate_write()
            controller = mock_factory.controllers(mock_factory.n_collaterals() - 1)
            added_debt += debt
            mock_factory.set_debt(controller, debt)
            total_debt, debt_for = mp.internal.get_total_debt(controller)
            assert total_debt == initial_debt + added_debt
            assert debt_for == debt
