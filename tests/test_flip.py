from pytest import mark  # noqa

# 1. deposit below (N > 0 in 5 bands)
# 2. change price_oracle in a cycle downwards (by 15% just in case?)
# 3. exchange until price is >= price_oracle (after changing price oracle down - current price goes down)
# 4. check flip down when at final price
# 5. repeat in other way
AMOUNT_D = 5 * 10**18
STEP = 0.1


# @mark.skip('not ready')
def test_flip(amm, PriceOracle, accounts, collateral_token, borrowed_token):
    admin = accounts[0]
    depositor = accounts[1]
    trader = accounts[2]

    # Current band is 0
    # We deposit to bands 1..5
    collateral_token._mint_for_testing(depositor, AMOUNT_D)
    amm.deposit_range(depositor, AMOUNT_D, 1, 5, True, {'from': admin})
    p = amm.price_oracle()

    initial_y = sum(amm.bands_y(n) for n in range(1, 6))

    # Buy until we have 0 coins left
    for i in range(20):
        p = p * 995 // 1000
        PriceOracle.set_price(p, {'from': admin})
        # Current price is proportional to p**3
        # which means that it becomes lower than p, and we need to buy until we have reached p

        # trade
        dx = int(STEP * AMOUNT_D * p / 1e18 / 10**(18-6))
        is_empty = False
        while amm.get_p() < p:
            borrowed_token._mint_for_testing(trader, dx)
            n1 = amm.active_band()
            p1 = amm.get_p()
            amm.exchange(0, 1, dx, 0, {'from': trader})
            n2 = amm.active_band()
            p2 = amm.get_p()
            if n1 == n2:
                assert p2 >= p1
            assert p2 >= amm.p_current_down(n2)
            assert p2 <= amm.p_current_up(n2)
            is_empty = sum(amm.bands_y(n) for n in range(1, 6)) == 0
            if is_empty:
                break
        if is_empty:
            break

    # Sell until we have 0 coins left
    for i in range(20):
        dy = int(STEP * AMOUNT_D)
        is_empty = False
        while amm.get_p() > p:
            if collateral_token.balanceOf(trader) < dy:
                collateral_token._mint_for_testing(trader, dy)
            n1 = amm.active_band()
            p1 = amm.get_p()
            print(n1, p1, amm.bands_x(n1), amm.bands_y(n1), is_empty)
            amm.exchange(1, 0, dy, 0, {'from': trader})
            n2 = amm.active_band()
            p2 = amm.get_p()
            if n1 == n2:
                assert p2 <= p1
            assert p2 >= amm.p_current_down(n2)
            assert p2 <= amm.p_current_up(n2)
            is_empty = sum(amm.bands_x(n) for n in range(1, 6)) == 0
            if is_empty:
                break

        if is_empty:
            break

        p = p * 1000 // 995
        PriceOracle.set_price(p, {'from': admin})
