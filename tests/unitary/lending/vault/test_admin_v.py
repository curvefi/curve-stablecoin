import boa


def test_admin(vault, factory, admin):
    """Test that vault admin changes when factory admin changes."""
    # Check that vault admin is the same as factory admin
    assert vault.admin() == factory.admin() == admin

    # Generate new admin
    new_admin = boa.env.generate_address()

    # Change factory admin
    factory.transfer_ownership(new_admin, sender=admin)

    # Check that vault admin is now the new factory admin
    assert vault.admin() == factory.admin() == new_admin
