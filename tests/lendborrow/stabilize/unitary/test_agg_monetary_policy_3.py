import boa
import pytest

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
    pass
