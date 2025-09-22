from tests.utils.constants import MAX_UINT256


def test_default_behavior(controller, vault, borrowed_token):
    # No need to check vault address and borrow cap in here
    # as their getter tests already do that.

    approved = borrowed_token.allowance(controller, vault)
    assert approved == MAX_UINT256
