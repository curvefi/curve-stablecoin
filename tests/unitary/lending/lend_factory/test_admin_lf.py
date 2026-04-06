import boa


def test_default_behavior(factory, admin, controller, vault):
    assert factory.admin() == admin

    assert factory.admin(controller.address) == admin
    assert factory.admin(vault.address) == admin

    with boa.env.prank(controller.address):
        assert factory.admin() == admin

    with boa.env.prank(vault.address):
        assert factory.admin() == admin


def test_change_default_admin(factory, admin):
    assert factory.admin() == admin
    new_admin = boa.env.generate_address("new_admin")

    with boa.env.prank(admin):
        factory.set_admin_group_assignee(0, new_admin)

    assert factory.admin() == new_admin


def test_custom_behavior(factory, admin, controller, vault):
    custom_admin = boa.env.generate_address("custom_admin")

    with boa.env.prank(admin):
        group_id = factory.add_admin_group(custom_admin)
        factory.set_admin_group(controller.address, group_id)
        factory.set_admin_group(vault.address, group_id)

    assert factory.admin(controller.address) == custom_admin
    assert factory.admin(vault.address) == custom_admin

    with boa.env.prank(controller.address):
        assert factory.admin() == custom_admin

    with boa.env.prank(vault.address):
        assert factory.admin() == custom_admin


def test_set_admin_group_assignee(factory, admin, controller):
    first_admin = boa.env.generate_address("first_admin")
    second_admin = boa.env.generate_address("second_admin")

    with boa.env.prank(admin):
        group_id = factory.add_admin_group(first_admin)
        factory.set_admin_group(controller.address, group_id)
        factory.set_admin_group_assignee(group_id, second_admin)

    assert factory.admin(controller.address) == second_admin


def test_unauthorized_set_admin_group(factory, controller):
    non_owner = boa.env.generate_address("non_owner")
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(non_owner):
            factory.set_admin_group(controller.address, 0)


def test_unauthorized_add_admin_group(factory):
    non_owner = boa.env.generate_address("non_owner")
    candidate_admin = boa.env.generate_address("candidate_admin")
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(non_owner):
            factory.add_admin_group(candidate_admin)


def test_unauthorized_set_admin_group_assignee(factory):
    non_owner = boa.env.generate_address("non_owner")
    new_admin = boa.env.generate_address("new_admin")
    with boa.reverts("ownable: caller is not the owner"):
        with boa.env.prank(non_owner):
            factory.set_admin_group_assignee(0, new_admin)
