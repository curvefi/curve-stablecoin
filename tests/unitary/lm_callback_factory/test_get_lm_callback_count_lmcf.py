import boa


def test_count_starts_at_zero(factory):
    assert factory.get_lm_callback_count() == 0


def test_count_increments_per_deployment(factory):
    for i in range(3):
        assert factory.get_lm_callback_count() == i
        factory.deploy_lm_callback(boa.env.generate_address(f"amm_{i}"))
        assert factory.get_lm_callback_count() == i + 1


def test_count_unchanged_by_failed_deployment(factory, dummy_amm, owner):
    factory.deploy_lm_callback(dummy_amm)
    factory.pause(sender=owner)

    with boa.reverts("pausable: contract is paused"):
        factory.deploy_lm_callback(dummy_amm)

    assert factory.get_lm_callback_count() == 1
