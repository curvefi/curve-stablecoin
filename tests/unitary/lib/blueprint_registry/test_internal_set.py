import boa


def test_default_behavior(blueprint_registry):
    # try to set a couple test values and get them
    blueprint_registry.eval(f'self.set("AMM", {boa.env.generate_address()})')
    blueprint_registry.eval(f'self.set("CTR", {boa.env.generate_address()})')


def test_invalid_id(blueprint_registry):
    # test setting a non allowed blueprint raises
    with boa.reverts(dev="blueprint id not allowed"):
        blueprint_registry.eval(f'self.set("XXXX", {boa.env.generate_address()})')
