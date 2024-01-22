def test_vault_creation(vault_long, vault_short,
                        controller_long, controller_short, amm_long, amm_short,
                        collateral_token, borrowed_token, price_oracle):
    assert controller_long.borrowed_token() == borrowed_token.address
    assert controller_short.borrowed_token() == collateral_token.address
    assert controller_long.collateral_token() == vault_short.address
    assert controller_short.collateral_token() == vault_long.address

    assert amm_long.price_oracle() == price_oracle.price() // 1000
    assert amm_short.price_oracle() == (10**18) ** 2 // 1000 // price_oracle.price()
