import boa
from pytest import mark  # noqa

# 1. deposit below (N > 0 in 5 bands)
# 2. change price_oracle in a cycle downwards (by 15% just in case?)
# 3. exchange until price is >= price_oracle (after changing price oracle down - current price goes down)
# 4. check flip down when at final price
# 5. repeat in other way
AMOUNT_D = 5 * 10**18
STEP = 0.01


def test_flip(amm, price_oracle, collateral_token, borrowed_token, accounts, admin):
    depositor = accounts[0]
    trader = accounts[1]

    with boa.env.anchor():
        # Current band is 0
        # We deposit to bands 1..5
        with boa.env.prank(admin):
            amm.deposit_range(depositor, AMOUNT_D, 1, 5)
            collateral_token._mint_for_testing(amm.address, AMOUNT_D)
        p = amm.price_oracle()

        initial_y = sum(amm.bands_y(n) for n in range(1, 6))

        # Buy until we have 0 coins left
        while True:
            p = p * 995 // 1000
            with boa.env.prank(admin):
                price_oracle.set_price(p)
            # Current price is proportional to p**3
            # which means that it becomes lower than p, and we need to buy until we have reached p

            # trade
            dx = int(STEP * AMOUNT_D * p / 1e18 / 10**(18-6))
            is_empty = False
            while amm.get_p() < p:
                borrowed_token._mint_for_testing(trader, dx)
                n1 = amm.active_band()
                p1 = amm.get_p()
                assert amm.get_y_up(depositor) * (1 + 1e-13) >= sum(amm.bands_y(n) for n in range(1, 6))
                assert amm.get_x_down(depositor) * (1 + 1e-13) >= 5 * 0.95 * 3000 * 1e6
                with boa.env.prank(trader):
                    amm.exchange(0, 1, dx, 0)
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

        converted_x = sum(amm.bands_x(n) for n in range(1, 6)) // 10**(18 - 6)
        assert converted_x >= 5 * 0.95**0.5 * amm.p_oracle_down(1)/1e18 * 1e6

        # Sell until we have 0 coins left
        while True:
            dy = int(STEP * AMOUNT_D)
            is_empty = False
            while amm.get_p() > p:
                if collateral_token.balanceOf(trader) < dy:
                    collateral_token._mint_for_testing(trader, dy)
                n1 = amm.active_band()
                p1 = amm.get_p()
                assert amm.get_y_up(depositor) * (1 + 1e-13) >= sum(amm.bands_y(n) for n in range(1, 6))
                assert amm.get_x_down(depositor) * (1 + 1e-13) >= 5 * 0.95 * 3000 * 1e6
                with boa.env.prank(trader):
                    amm.exchange(1, 0, dy, 0)
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
            with boa.env.prank(admin):
                price_oracle.set_price(p)

        # That actually wouldn't necessarily happen: could be a loss easily
        # But this time, AMM made more money than lost
        # We wanted to check if the loss is not too small, but in reality got a gain
        assert amm.get_x_down(depositor) * (1 + 1e-13) >= converted_x
        assert sum(amm.bands_y(n) for n in range(1, 6)) >= initial_y
