def test_vault(vault, market_controller, market_amm, market_mpolicy):
    assert vault.amm() == market_amm.address
    assert vault.controller() == market_controller.address
    assert market_controller.monetary_policy() == market_mpolicy.address
