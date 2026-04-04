from snekmate.auth import ownable
from curve_std.utils import role_bindings

uses: ownable
uses: role_bindings


FEE_RECEIVER_ROLE: constant(uint256) = 1  # Generally used in LendController


@deploy
def __init__(_default_fee_receiver: address):
    role_bindings._init_role(FEE_RECEIVER_ROLE, _default_fee_receiver)


@external
def set_fee_receiver_group(_controller: address, _group_id: uint256):
    """
    @notice Assign a _controller to fee_receiver group.
    @param _controller Controller address.
    @param _group_id Custom fee receiver group.
    """
    ownable._check_owner()
    role_bindings._bind_subject_to_group(FEE_RECEIVER_ROLE, _controller, _group_id)


@external
def add_fee_receiver_group(_fee_receiver: address) -> uint256:
    """
    @notice Create a new fee receiver group.
    @param _fee_receiver Address for the new group fee receiver.
    @return group_id The id assigned to the new group.
    """
    ownable._check_owner()
    return role_bindings._add_role_group(FEE_RECEIVER_ROLE, _fee_receiver)


@external
def set_fee_receiver_group_assignee(_group_id: uint256, _fee_receiver: address):
    """
    @notice Replace the fee receiver address for a group.
    @param _group_id Fee receiver group id.
    @param _fee_receiver New fee receiver.
    """
    ownable._check_owner()
    role_bindings._set_group_assignee(FEE_RECEIVER_ROLE, _group_id, _fee_receiver)


@external
@view
def fee_receiver(_controller: address = msg.sender) -> address:
    """
    @notice Get fee receiver who earns interest from admin fees
    @dev This function is called by controllers without specifying the
    first argument to get their fee receiver.
    @param _controller Address of the controller
    """
    return role_bindings._resolve_assignee_of(FEE_RECEIVER_ROLE, _controller)
