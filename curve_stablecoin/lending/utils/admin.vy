from snekmate.auth import ownable
from curve_std.utils import role_bindings

uses: ownable
uses: role_bindings

ADMIN_ROLE: constant(uint256) = 0  # Generally used in Vault, LendController


@deploy
def __init__(_default_admin: address):
    role_bindings._init_role(ADMIN_ROLE, _default_admin)


@external
def set_admin_group(_contract: address, _group_id: uint256):
    """
    @notice Assign a contract to an admin group.
    @param _contract Contract address.
    @param _group_id Custom admin group.
    """
    ownable._check_owner()
    role_bindings._bind_subject_to_group(ADMIN_ROLE, _contract, _group_id)


@external
def add_admin_group(_admin: address) -> uint256:
    """
    @notice Create a new admin group.
    @param _admin Address for the new group admin.
    @return group_id The id assigned to the new group.
    """
    ownable._check_owner()
    return role_bindings._add_role_group(ADMIN_ROLE, _admin)


@external
def set_admin_group_assignee(_group_id: uint256, _admin: address):
    """
    @notice Replace the admin address for a group.
    @param _group_id Admin group id.
    @param _admin New admin address.
    """
    ownable._check_owner()
    role_bindings._set_group_assignee(ADMIN_ROLE, _group_id, _admin)


@external
@view
def admin(_contract: address = msg.sender) -> address:
    # Use for Controller and Vault
    return role_bindings._resolve_assignee_of(ADMIN_ROLE, _contract)
