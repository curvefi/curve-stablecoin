import pytest
import boa
from tests.utils.deployers import (
    MINT_CONTROLLER_DEPLOYER,
    LL_CONTROLLER_DEPLOYER,
    AMM_DEPLOYER,
    DUMMY_PRICE_ORACLE_DEPLOYER,
    ERC20_MOCK_DEPLOYER,
)
from tests.utils.constants import MAX_UINT256, MAX_ORACLE_PRICE_DEVIATION


@pytest.fixture(scope="module")
def decimals():
    # Overrides global fixture as these tests don't
    # change behavior with different decimals
    return 18

@pytest.fixture()
def mint_market(proto, collat):
    return proto.create_mint_market(
        collat,
        proto.price_oracle,
        proto.mint_monetary_policy,
        A=1000,
        amm_fee=10**16,
        admin_fee=0,
        loan_discount= int(0.09 * 10**18),
        liquidation_discount=int(0.06 * 10**18),
        debt_ceiling=1000 * 10**18
    )


@pytest.fixture()
def lend_market(proto, collat):
    return proto.create_lending_market(
        borrowed_token=proto.crvUSD, # TODO param other tokens
        collateral_token=collat,
        A=1000,
        fee=10**16,
        loan_discount=int(0.09 * 10**18),
        liquidation_discount=int(0.06 * 10**18),
        price_oracle=proto.price_oracle,
        name="Test Vault",
        min_borrow_rate=10**15 // (365 * 86400),  # 0.1% APR (per second)
        max_borrow_rate=10**18 // (365 * 86400)    # 100% APR (per second)
    )

@pytest.fixture(params=["mint", "lending"])
def market(request, mint_market, lend_market):
    """Parametrized fixture that provides both mint and lending markets."""
    if request.param == "mint":
        return mint_market
    else:
        return lend_market

@pytest.fixture()
def controller(market):
    """Parametrized controller fixture that works with both market types."""
    # Check if it's a mint market by looking for 'controller' key structure
    # Mint markets have 'controller' and 'amm'
    # Lending markets have 'vault', 'controller', 'amm', 'oracle', 'monetary_policy'
    if 'vault' in market:
        # It's a lending market
        return LL_CONTROLLER_DEPLOYER.at(market['controller'])
    else:
        # It's a mint market
        return MINT_CONTROLLER_DEPLOYER.at(market['controller'])

@pytest.fixture()
def amm(market):
    return AMM_DEPLOYER.at(market['amm'])


@pytest.fixture(scope="module")
def new_oracle(admin):
    """Deploy a new price oracle for testing."""
    return DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, 3000 * 10**18, sender=admin)


@pytest.fixture(scope="module")
def different_price_oracle(admin):
    """Deploy an oracle with a different price for testing price deviation."""
    # 10% higher price
    return DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, 3300 * 10**18, sender=admin)


@pytest.fixture(scope="module")
def high_deviation_oracle(admin):
    """Deploy an oracle with high price deviation for testing."""
    # 60% higher price - exceeds MAX_ORACLE_PRICE_DEVIATION
    return DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, 4800 * 10**18, sender=admin)


def test_default_behavior(controller, amm, new_oracle, admin):
    """Test normal oracle update with valid parameters."""
    initial_oracle = amm.price_oracle_contract()
    assert initial_oracle != new_oracle
    
    # Set new oracle with reasonable max deviation
    max_deviation = 10**17  # 10%
    controller.set_price_oracle(new_oracle, max_deviation, sender=admin)
    
    # Verify oracle was updated on AMM
    assert amm.price_oracle_contract() == new_oracle.address


def test_admin_access_control(controller, new_oracle):
    """Test that only admin can call set_price_oracle."""
    max_deviation = 10**17  # 10%
    
    with boa.reverts("only admin"):
        controller.set_price_oracle(new_oracle, max_deviation)


def test_max_deviation_validation_too_high(controller, new_oracle, admin):
    """Test that max_deviation cannot exceed MAX_ORACLE_PRICE_DEVIATION."""
    # MAX_ORACLE_PRICE_DEVIATION is 50% (WAD // 2)
    invalid_deviation = MAX_ORACLE_PRICE_DEVIATION + 1
    
    with boa.reverts(dev="invalid max deviation"):
        controller.set_price_oracle(new_oracle, invalid_deviation, sender=admin)


def test_max_deviation_validation_boundary(controller, new_oracle, admin, amm):
    """Test that exactly MAX_ORACLE_PRICE_DEVIATION is accepted."""
    # Should succeed at boundary
    controller.set_price_oracle(new_oracle, MAX_ORACLE_PRICE_DEVIATION, sender=admin)
    assert amm.price_oracle_contract() == new_oracle.address


def test_max_deviation_skip_check(controller, high_deviation_oracle, admin, amm, proto):
    """Test that max_value(uint256) skips deviation check."""
    # Verify high_deviation_oracle is ~60% higher than initial oracle
    initial_price = proto.price_oracle.price()
    high_price = high_deviation_oracle.price()
    expected_price = initial_price * 160 // 100  # 60% higher
    assert abs(high_price - expected_price) < initial_price // 100  # Within 1% tolerance
    
    # Even with high price deviation, should succeed when max_deviation is max_value
    controller.set_price_oracle(high_deviation_oracle, MAX_UINT256, sender=admin)
    assert amm.price_oracle_contract() == high_deviation_oracle.address


@pytest.fixture(scope="module")
def broken_oracle():
    """Deploy a broken oracle without required methods."""
    # This is just a plain ERC20 that doesn't have price() or price_w() methods
    return ERC20_MOCK_DEPLOYER.deploy(18)


def test_oracle_validation_missing_methods(controller, broken_oracle, admin):
    """Test that oracle without required methods reverts."""
    max_deviation = 10**17  # 10%
    
    # Should revert when trying to call price_w() on broken oracle
    with boa.reverts():
        controller.set_price_oracle(broken_oracle, max_deviation, sender=admin)


def test_price_deviation_check_within_limit(controller, different_price_oracle, admin, amm):
    """Test successful update when price deviation is within limit."""
    # 10% price difference, 20% max deviation allowed
    max_deviation = 2 * 10**17  # 20%
    
    controller.set_price_oracle(different_price_oracle, max_deviation, sender=admin)
    assert amm.price_oracle_contract() == different_price_oracle.address


def test_price_deviation_check_exceeds_limit(controller, different_price_oracle, admin):
    """Test that update fails when price deviation exceeds limit."""
    # 10% price difference, but only 5% max deviation allowed
    max_deviation = 5 * 10**16  # 5%
    
    with boa.reverts("delta>max"):
        controller.set_price_oracle(different_price_oracle, max_deviation, sender=admin)


def test_price_deviation_calculation_higher_new_price(controller, admin, amm):
    """Test deviation calculation when new price is higher than old."""
    # Create oracle with 15% higher price
    higher_price_oracle = DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, 3450 * 10**18, sender=admin)
    
    # Should succeed with 20% max deviation
    controller.set_price_oracle(higher_price_oracle, 2 * 10**17, sender=admin)
    assert amm.price_oracle_contract() == higher_price_oracle.address


def test_price_deviation_calculation_lower_new_price(controller, admin, amm):
    """Test deviation calculation when new price is lower than old."""
    # Create oracle with 15% lower price
    lower_price_oracle = DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, 2550 * 10**18, sender=admin)
    
    # Should succeed with 20% max deviation
    controller.set_price_oracle(lower_price_oracle, 2 * 10**17, sender=admin)
    assert amm.price_oracle_contract() == lower_price_oracle.address


def test_price_deviation_at_exact_limit(controller, admin, amm):
    """Test oracle update at exact deviation limit."""
    # Create oracle with exactly 10% higher price
    exact_limit_oracle = DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, 3300 * 10**18, sender=admin)
    
    # Should succeed with exactly 10% max deviation
    controller.set_price_oracle(exact_limit_oracle, 10**17, sender=admin)
    assert amm.price_oracle_contract() == exact_limit_oracle.address


def test_same_price_different_oracle(controller, admin, amm):
    """Test updating to a new oracle with the same price."""
    # Create oracle with same price as initial
    same_price_oracle = DUMMY_PRICE_ORACLE_DEPLOYER.deploy(admin, 3000 * 10**18, sender=admin)
    
    # Should succeed even with 0 deviation allowed
    controller.set_price_oracle(same_price_oracle, 0, sender=admin)
    assert amm.price_oracle_contract() == same_price_oracle.address


