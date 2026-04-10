def test_default_behavior_market_count_increments(
    factory,
    proto,
    borrowed_token,
    collateral_token,
    price_oracle,
    amm_A,
    amm_fee,
    loan_discount,
    liquidation_discount,
    min_borrow_rate,
    max_borrow_rate,
    seed_liquidity,
    lending_monetary_policy,
):
    before_count = factory.market_count()

    proto.create_lending_market(
        borrowed_token=borrowed_token,
        collateral_token=collateral_token,
        A=amm_A,
        fee=amm_fee,
        loan_discount=loan_discount,
        liquidation_discount=liquidation_discount,
        price_oracle=price_oracle,
        min_borrow_rate=min_borrow_rate,
        max_borrow_rate=max_borrow_rate,
        seed_amount=seed_liquidity,
        mpolicy_deployer=lending_monetary_policy,
    )

    after_count = factory.market_count()
    assert after_count == before_count + 1
