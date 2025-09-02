import boa
import pytest
from tests.utils.deployers import FAKE_LEVERAGE_DEPLOYER, ERC20_MOCK_DEPLOYER

@pytest.fixture(scope="module", params=[True, False])
def tokens_for_vault(admin, stablecoin, decimals, request):
    stablecoin_is_borrowed = request.param
    with boa.env.prank(admin):
        token = ERC20_MOCK_DEPLOYER.deploy(decimals)
    if stablecoin_is_borrowed:
        borrowed_token = stablecoin
        collateral_token = token
    else:
        borrowed_token = token
        collateral_token = stablecoin
    return borrowed_token, collateral_token


@pytest.fixture(scope="module")
def collateral_token(tokens_for_vault):
    return tokens_for_vault[1]


@pytest.fixture(scope="module")
def borrowed_token(tokens_for_vault):
    return tokens_for_vault[0]


@pytest.fixture(scope="module")
def lending_market(proto, borrowed_token, collateral_token, price_oracle, admin):
    with boa.env.prank(admin):
        result = proto.create_lending_market(
            borrowed_token=borrowed_token,
            collateral_token=collateral_token,
            A=100,
            fee=int(0.006 * 1e18),
            loan_discount=int(0.09 * 1e18),
            liquidation_discount=int(0.06 * 1e18),
            price_oracle=price_oracle,
            name="Test vault",
            min_borrow_rate=int(0.005 * 1e18) // (365 * 86400),  # 0.5% APR
            max_borrow_rate=int(0.5 * 1e18) // (365 * 86400)  # 50% APR
        )
        return result


@pytest.fixture(scope="module")
def vault(lending_market):
    return lending_market['vault']


@pytest.fixture(scope="module")
def market_controller(lending_market, admin):
    controller = lending_market['controller']
    with boa.env.prank(admin):
        controller.set_borrow_cap(2**256 - 1)
    return controller


@pytest.fixture(scope="module")
def market_amm(lending_market):
    return lending_market['amm']


@pytest.fixture(scope="module")
def monetary_policy(market_controller, borrowed_token, admin):
    from tests.utils.deployers import SEMILOG_MONETARY_POLICY_DEPLOYER
    # Override default policy with Semilog for lending test suite
    min_borrow_rate = int(0.005 * 1e18) // (365 * 86400)  # 0.5% APR
    max_borrow_rate = int(0.5 * 1e18) // (365 * 86400)   # 50% APR
    with boa.env.prank(admin):
        mp = SEMILOG_MONETARY_POLICY_DEPLOYER.deploy(
            borrowed_token.address,
            min_borrow_rate,
            max_borrow_rate,
        )
        market_controller.set_monetary_policy(mp)
    return mp


@pytest.fixture(scope="module")
def filled_controller(vault, borrowed_token, market_controller, admin):
    with boa.env.prank(admin):
        amount = 100 * 10**6 * 10**(borrowed_token.decimals())
        boa.deal(borrowed_token, admin, amount)
        borrowed_token.approve(vault.address, 2**256 - 1)
        vault.deposit(amount)
    return market_controller


@pytest.fixture(scope="module")
def fake_leverage(collateral_token, borrowed_token, market_controller, admin):
    with boa.env.prank(admin):
        leverage = FAKE_LEVERAGE_DEPLOYER.deploy(borrowed_token.address, collateral_token.address,
                            market_controller.address, 3000 * 10**18)
        boa.deal(collateral_token, leverage.address, 1000 * 10**collateral_token.decimals())
        return leverage
