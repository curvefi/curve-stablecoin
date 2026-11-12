def test_lp_token(lm_callback, collateral_token):
    assert lm_callback.lp_token() == collateral_token.address
