import boa


def test_admin(vault, factory, admin):
    """Test that vault admin follows the factory admin role assignee."""
    # Check that vault admin is the same as factory admin
    assert vault.admin() == factory.admin() == admin

    # Generate new admin
    new_admin = boa.env.generate_address()

    # Change default factory admin role assignee
    factory.set_admin_group_assignee(0, new_admin, sender=admin)

    # Check that vault admin is now the new factory admin
    assert vault.admin() == factory.admin() == new_admin
