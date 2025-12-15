import boa


def test_default_behavior(blueprint_registry):
    addr_amm = boa.env.generate_address()
    blueprint_registry.eval(f'self.set("AMM", {addr_amm})')
    assert blueprint_registry.eval('self.get("AMM")') == addr_amm


def test_zero_address(blueprint_registry):
    # test getting a non existent blueprint raises
    with boa.reverts(dev="blueprint not found"):
        blueprint_registry.eval('self.get("CTR")')  # Valid ID but not set

    with boa.reverts(dev="blueprint not found"):
        blueprint_registry.eval('self.get("XXXX")')  # Invalid ID and not set
