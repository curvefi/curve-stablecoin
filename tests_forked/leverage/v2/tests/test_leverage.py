class TestLeverage:
    class TestCreateLoan:
        def test_max_borrowable(self, alice, collateral, controller, leverage_zap_1inch, router_api_1inch):
            N = 4
            max_collateral = 0
            collateral_decimals = 10 ** collateral.decimals()
            p_avg = 10**18 * collateral_decimals // router_api_1inch.get_rate(collateral.address, 1 * 10**18)
            balance = 1 * 10**18 if collateral.symbol() == "WETH" else collateral.balanceOf(alice)

            max_borrowable = leverage_zap_1inch.max_borrowable(controller.address, balance, max_collateral, N, p_avg)

            max_collateral = router_api_1inch.get_rate(collateral.address, max_borrowable)
            p_avg = max_borrowable * collateral_decimals // max_collateral
            max_borrowable = leverage_zap_1inch.max_borrowable(controller.address, balance, max_collateral, N, p_avg)

            assert max_borrowable > 0
