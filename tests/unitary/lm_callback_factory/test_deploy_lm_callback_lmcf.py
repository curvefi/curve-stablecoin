import boa
import pytest

from tests.utils.constants import ZERO_ADDRESS
from tests.utils.deployers import DUMMY_LM_CALLBACK_DEPLOYER, compiler_args_default

# Re-enters `deploy_lm_callback` from inside the blueprint constructor - the exact
# hand-off of control the `@nonreentrant` lock exists to close. `revert_on_failure`
# is off so the constructor survives the blocked call and the outer deploy can be
# inspected afterwards.
REENTRANT_CALLBACK = """
# pragma version 0.4.3

@deploy
def __init__(_amm: address):
    success: bool = False
    response: Bytes[32] = b""
    success, response = raw_call(
        msg.sender,
        concat(method_id("deploy_lm_callback(address)"), convert(_amm, bytes32)),
        max_outsize=32,
        revert_on_failure=False,
    )
    assert not success, "reentrancy was not blocked"
"""


def test_deploy_returns_the_deployed_callback(factory, dummy_amm):
    lm_callback = factory.deploy_lm_callback(dummy_amm)

    assert lm_callback != ZERO_ADDRESS
    assert boa.env.get_code(lm_callback) != b""


def test_deploy_uses_blueprint_and_forwards_amm(factory, dummy_amm):
    lm_callback = factory.deploy_lm_callback(dummy_amm)

    # Vyper appends immutables to the runtime bytecode, so an identical direct
    # deployment proves both the blueprint used and the forwarded `amm` argument
    reference = DUMMY_LM_CALLBACK_DEPLOYER.deploy(dummy_amm)
    assert boa.env.get_code(lm_callback) == boa.env.get_code(reference.address)


def test_deploy_registers_the_callback(factory, dummy_amm):
    lm_callback = factory.deploy_lm_callback(dummy_amm)

    assert factory.is_valid_lm_callback(lm_callback)
    assert factory.get_lm_callback_count() == 1
    assert factory.get_lm_callback(0) == lm_callback


def test_deploy_emits_event(factory, dummy_amm, lm_callback_blueprint, single_factory_event):
    deployer = boa.env.generate_address("deployer")
    lm_callback = factory.deploy_lm_callback(dummy_amm, sender=deployer)

    log = single_factory_event(factory, "DeployedLMCallback")
    assert log.amm == dummy_amm
    assert log.deployer == deployer
    assert log.blueprint == lm_callback_blueprint.address
    assert log.lm_callback == lm_callback


def test_deploy_is_permissionless(factory, dummy_amm, owner):
    anyone = boa.env.generate_address("anyone")
    assert anyone != owner

    lm_callback = factory.deploy_lm_callback(dummy_amm, sender=anyone)

    assert factory.is_valid_lm_callback(lm_callback)


def test_deploy_appends_in_order(factory):
    amms = [boa.env.generate_address(f"amm_{i}") for i in range(3)]

    lm_callbacks = [factory.deploy_lm_callback(amm) for amm in amms]

    assert len(set(lm_callbacks)) == len(lm_callbacks)
    assert factory.get_lm_callback_count() == 3
    for i, lm_callback in enumerate(lm_callbacks):
        assert factory.get_lm_callback(i) == lm_callback
        assert factory.is_valid_lm_callback(lm_callback)


def test_deploy_allows_several_callbacks_per_amm(factory, dummy_amm):
    """Nothing dedupes by AMM: the same market can back more than one callback."""
    first = factory.deploy_lm_callback(dummy_amm)
    second = factory.deploy_lm_callback(dummy_amm)

    assert first != second
    assert factory.is_valid_lm_callback(first)
    assert factory.is_valid_lm_callback(second)


def test_deploy_reverts_when_paused(paused_factory, dummy_amm):
    with boa.reverts("pausable: contract is paused"):
        paused_factory.deploy_lm_callback(dummy_amm)


def test_deploy_works_again_after_unpause(paused_factory, dummy_amm, owner):
    paused_factory.unpause(sender=owner)

    lm_callback = paused_factory.deploy_lm_callback(dummy_amm)

    assert paused_factory.is_valid_lm_callback(lm_callback)


def test_deploy_reverts_when_blueprint_has_no_code(deploy_factory, owner, dummy_amm):
    """A codeless blueprint is only caught here, at `create_from_blueprint`."""
    factory = deploy_factory(owner, boa.env.generate_address("not_a_blueprint"))

    with boa.reverts():
        factory.deploy_lm_callback(dummy_amm)


def test_deploy_reverts_when_constructor_reverts(deploy_factory, owner, dummy_amm):
    reverting_blueprint = boa.loads_partial(
        """
# pragma version 0.4.3

@deploy
def __init__(_amm: address):
    raise "constructor failed"
""",
        compiler_args=compiler_args_default,
    ).deploy_as_blueprint()
    factory = deploy_factory(owner, reverting_blueprint)

    with boa.reverts("constructor failed"):
        factory.deploy_lm_callback(dummy_amm)

    assert factory.get_lm_callback_count() == 0


def test_deploy_is_not_reentrant(deploy_factory, owner, dummy_amm):
    reentrant_blueprint = boa.loads_partial(
        REENTRANT_CALLBACK, compiler_args=compiler_args_default
    ).deploy_as_blueprint()
    factory = deploy_factory(owner, reentrant_blueprint)

    lm_callback = factory.deploy_lm_callback(dummy_amm)

    # The nested deploy was rejected, so only the outer one is on the registry
    assert factory.get_lm_callback_count() == 1
    assert factory.get_lm_callback(0) == lm_callback


@pytest.mark.parametrize("amm", [ZERO_ADDRESS, "0x" + "11" * 20])
def test_deploy_does_not_validate_the_amm(factory, amm):
    """The factory takes the AMM on trust; it never checks it is a real market."""
    lm_callback = factory.deploy_lm_callback(amm)

    assert factory.is_valid_lm_callback(lm_callback)
