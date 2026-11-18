# pragma version 0.4.3
"""
@title CurveLMCallbackFactory

@author Curve.Finance
@license Copyright (c) Curve.Finance, 2020-2026 - all rights reserved
@notice Factory for Curve LlamaLend Liquidity Mining Callbacks
@custom:security security@curve.finance
@custom:kill Call pause() via owner to halt new LM Callback deployments
"""

from curve_stablecoin.interfaces import IAMM
from curve_stablecoin.interfaces import ILMCallbackFactory

version: public(constant(String[5])) = "1.0.0"

implements: ILMCallbackFactory

from snekmate.auth import ownable
from snekmate.utils import pausable

initializes: ownable
initializes: pausable

exports: (
    # `renounce_ownership` is intentionally not exported: with a zero owner the
    # blueprint could never be updated again
    ownable.owner,
    ownable.transfer_ownership,
    pausable.paused,
)


MAX_LM_CALLBACKS: constant(uint256) = 10**18

lm_callback_blueprint: public(address)
# Named after the gauge factories' getter rather than after the callback:
# integrations validate a gauge by asking its factory for `is_valid_gauge`,
# and LM Callbacks are gauges from their point of view
is_valid_gauge: public(HashMap[address, bool])
# The newest callback this factory deployed for an AMM - deploy-time intent, not
# live state: the Configurator can attach any address it likes, and a detach is
# never reflected here. Ask the AMM itself for what is currently attached
get_lm_callback_by_amm: public(HashMap[address, address])
# Blueprint each callback was created from, kept for the duplicate check in
# `deploy_lm_callback` and so integrations can tell callback generations apart
get_blueprint_by_lm_callback: public(HashMap[address, address])

_lm_callbacks: DynArray[address, MAX_LM_CALLBACKS]


@deploy
def __init__(
    _owner: address,
    _blueprint: address,
):
    """
    @notice Factory which creates LM Callbacks for LlamaLend/crvUSD markets from a blueprint
    @param _owner Owner of the factory, allowed to update the blueprint (ideally DAO)
    @param _blueprint Address of the LM Callback blueprint
    """
    ownable.__init__()
    pausable.__init__()
    assert _owner != empty(address)  # dev: zero owner
    ownable._transfer_ownership(_owner)

    self._set_blueprint(_blueprint)


@external
@nonreentrant
def deploy_lm_callback(_amm: IAMM) -> address:
    """
    @notice Deploy an LM Callback
    @dev Reentrancy-locked because the blueprint constructor hands control to
    the caller-supplied `_amm`; the lock keeps the registry writes below
    atomic with respect to the deployment they describe
    @dev Reverts if the AMM's newest callback came from the blueprint currently
    set, so a market cannot be handed two identical callbacks back to back.
    Only that newest callback is compared, not every one ever deployed for the
    AMM: rotating the blueprint away and back therefore does allow another
    deployment from the earlier blueprint
    @param _amm LlamaLend AMM the deployed LM Callback is going to be used for
    @return Address of the deployed LM Callback
    """
    pausable._require_not_paused()

    lm_callback_blueprint: address = self.lm_callback_blueprint
    existing_lm_callback: address = self.get_lm_callback_by_amm[_amm.address]
    if existing_lm_callback != empty(address):
        assert (
            self.get_blueprint_by_lm_callback[existing_lm_callback]
            != lm_callback_blueprint
        ), "already deployed"

    lm_callback: address = create_from_blueprint(
        lm_callback_blueprint,
        _amm,
        code_offset=3,
    )

    self.is_valid_gauge[lm_callback] = True
    self._lm_callbacks.append(lm_callback)
    self.get_lm_callback_by_amm[_amm.address] = lm_callback
    self.get_blueprint_by_lm_callback[lm_callback] = lm_callback_blueprint

    log ILMCallbackFactory.DeployedLMCallback(
        amm=_amm.address,
        deployer=msg.sender,
        blueprint=lm_callback_blueprint,
        lm_callback=lm_callback,
    )

    return lm_callback


@external
@view
def get_lm_callback(_i: uint256) -> address:
    """
    @notice Get the LM Callback deployed at index `_i`
    @param _i Index of the LM Callback
    @return Address of the LM Callback
    """
    return self._lm_callbacks[_i]


@external
@view
def get_lm_callback_count() -> uint256:
    """
    @notice Get the number of LM Callbacks deployed by this factory
    @return Number of deployed LM Callbacks
    """
    return len(self._lm_callbacks)


@external
def pause():
    """
    @notice Pause new LM Callback deployments
    """
    ownable._check_owner()
    pausable._pause()


@external
def unpause():
    """
    @notice Unpause the factory to allow new LM Callback deployments
    """
    ownable._check_owner()
    pausable._unpause()


@external
def set_blueprint(_blueprint: address):
    """
    @notice Set the blueprint
    @dev Reverts on the empty address: the blueprint can be rotated but never
    unset, so deployments are halted with pause() instead
    @param _blueprint The address of the blueprint to use
    """
    ownable._check_owner()
    self._set_blueprint(_blueprint)


@internal
def _set_blueprint(_blueprint: address):
    assert _blueprint != empty(address)  # dev: zero blueprint
    log ILMCallbackFactory.UpdateLMCallbackBlueprint(
        old_blueprint=self.lm_callback_blueprint, new_blueprint=_blueprint
    )
    self.lm_callback_blueprint = _blueprint
