import boa


def test_get_lm_callback_returns_deployment_order(factory):
    lm_callbacks = [
        factory.deploy_lm_callback(boa.env.generate_address(f"amm_{i}")) for i in range(3)
    ]

    for i, lm_callback in enumerate(lm_callbacks):
        assert factory.get_lm_callback(i) == lm_callback


def test_get_lm_callback_reverts_when_empty(factory):
    with boa.reverts():
        factory.get_lm_callback(0)


def test_get_lm_callback_reverts_past_the_end(factory, dummy_amm):
    factory.deploy_lm_callback(dummy_amm)

    with boa.reverts():
        factory.get_lm_callback(1)
