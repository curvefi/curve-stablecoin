import boa
import pytest
from tests.utils.deployers import (
    ERC20_CRV_DEPLOYER,
    VOTING_ESCROW_DEPLOYER,
    GAUGE_CONTROLLER_DEPLOYER,
    MINTER_DEPLOYER,
    LM_CALLBACK_DEPLOYER,
    LM_CALLBACK_FACTORY_DEPLOYER,
)
from tests.utils.constants import MAX_UINT256, ZERO_ADDRESS

# `LMCallback` hardcodes the mainnet CRV, GaugeController and Minter addresses so
# that it carries no constructor arguments beyond the AMM. The mocks are deployed
# over those addresses rather than the source being rewritten, so these tests run
# the exact bytecode that ships.
CRV_ADDRESS = "0xD533a949740bb3306d119CC777fa900bA034cd52"
GAUGE_CONTROLLER_ADDRESS = "0x2F50D538606Fa9EDD2B11E2446BEb18C9D5846bB"
MINTER_ADDRESS = "0xd061D61a4d941c39E5453435B6345Dc261C2fcE0"


# ── Market-parameter overrides ─────────────────────────────────────────────────


# We are going to use only Curve LPs with LMCallback
@pytest.fixture(scope="module")
def collateral_decimals():
    return 18


# Borrowed decimals don't matter
@pytest.fixture(scope="module")
def borrowed_decimals():
    return 18


@pytest.fixture(scope="module")
def loan_discount():
    return 5 * 10**16


@pytest.fixture(scope="module")
def liquidation_discount():
    return 2 * 10**16


@pytest.fixture(scope="module")
def min_borrow_rate():
    return 0


@pytest.fixture(scope="module")
def max_borrow_rate():
    return 0


@pytest.fixture(scope="module")
def seed_liquidity(borrowed_token):
    # Large enough to cover the test amounts (e.g. 10**21 * 2600 per user)
    return 10**8 * 10 ** borrowed_token.decimals()


# ── CRV ecosystem ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def crv(admin):
    with boa.env.prank(admin):
        return ERC20_CRV_DEPLOYER.deploy(
            "Curve DAO Token", "CRV", 18, override_address=CRV_ADDRESS
        )


@pytest.fixture(scope="module")
def voting_escrow(admin, crv):
    with boa.env.prank(admin):
        return VOTING_ESCROW_DEPLOYER.deploy(
            crv, "Voting-escrowed CRV", "veCRV", "veCRV_0.99"
        )


@pytest.fixture(scope="module")
def gauge_controller(admin, crv, voting_escrow):
    with boa.env.prank(admin):
        gc = GAUGE_CONTROLLER_DEPLOYER.deploy(
            crv, voting_escrow, override_address=GAUGE_CONTROLLER_ADDRESS
        )
        gc.add_type("crvUSD Market")
        gc.change_type_weight(0, 10**18)
        return gc


@pytest.fixture(scope="module")
def minter(admin, crv, gauge_controller):
    with boa.env.prank(admin):
        _minter = MINTER_DEPLOYER.deploy(
            crv, gauge_controller, override_address=MINTER_ADDRESS
        )
        crv.set_minter(_minter)
        return _minter


# ── LM Callback factory ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def lm_callback_factory(admin, minter):
    """
    Factory that deploys the callbacks under test.

    A callback records its deployer as `factory()`, so tests go through the real
    factory to get the same wiring production has. Depends on `minter` to pull in
    the whole CRV ecosystem, which the callback constructor reaches out to at its
    hardcoded addresses.
    """
    with boa.env.prank(admin):
        blueprint = LM_CALLBACK_DEPLOYER.deploy_as_blueprint()
        return LM_CALLBACK_FACTORY_DEPLOYER.deploy(admin, blueprint)


@pytest.fixture(scope="module")
def deploy_lm_callback(admin, lm_callback_factory):
    """
    Deploy a callback for `amm` through the factory and wrap it for tests.

    The factory refuses a second callback for an AMM while the blueprint it was
    deployed from is still the current one. Tests that need a fresh callback for
    an AMM that already has one - a replacement, or one deliberately left
    unattached - therefore rotate a new blueprint in first, which is the same
    escape hatch production has.
    """

    def _deploy(amm):
        with boa.env.prank(admin):
            existing = lm_callback_factory.get_lm_callback_by_amm(amm.address)
            blueprint = lm_callback_factory.lm_callback_blueprint()
            if (
                existing != ZERO_ADDRESS
                and lm_callback_factory.get_blueprint_by_lm_callback(existing)
                == blueprint
            ):
                lm_callback_factory.set_blueprint(
                    LM_CALLBACK_DEPLOYER.deploy_as_blueprint()
                )
            address = lm_callback_factory.deploy_lm_callback(amm)
        return LM_CALLBACK_DEPLOYER.at(address)

    return _deploy


# ── Actors ────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def trader(borrowed_token, collateral_token, amm):
    _trader = boa.env.generate_address("trader")
    boa.deal(borrowed_token, _trader, 10**25)
    boa.deal(collateral_token, _trader, 10**25)
    with boa.env.prank(_trader):
        borrowed_token.approve(amm, MAX_UINT256)
        collateral_token.approve(amm, MAX_UINT256)
    return _trader


# ── LM Callback ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def lm_callback(
    admin, amm, gauge_controller, controller, configurator, deploy_lm_callback
):
    cb = deploy_lm_callback(amm)
    with boa.env.prank(admin):
        configurator.set_callback(controller, cb)
        gauge_controller.add_gauge(cb.address, 0, 10**18)
    return cb
