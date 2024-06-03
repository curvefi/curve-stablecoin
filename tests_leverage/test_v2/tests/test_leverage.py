import pytest


class TestLeverage:

    def get_max_borrowable(
        self,
        collateral,
        stablecoin,
        controller,
        user_collateral_amount,
        leverage_zap_1inch,
        router_api_1inch,
        N,
    ):
        collateral_decimals = 10 ** collateral.decimals()
        stablecoin_decimals = 10 ** stablecoin.decimals()

        router_rate = router_api_1inch.get_rate_to_crvusd(
            collateral.address, user_collateral_amount * 10
        )
        avg_rate_initial = (
            router_rate
            * collateral_decimals
            / (user_collateral_amount * 10 * stablecoin_decimals)
        )
        p_avg_initial = int(avg_rate_initial * 10**18)
        lev_collateral_amount = 0
        max_b = leverage_zap_1inch.max_borrowable(
            controller.address,
            user_collateral_amount,
            lev_collateral_amount,
            N,
            p_avg_initial,
        )

        col_from_max_b = router_api_1inch.get_rate_from_crvusd(
            collateral.address, max_b
        )
        avg_rate = max_b * collateral_decimals / (col_from_max_b * stablecoin_decimals)
        p_avg = int(avg_rate * 10**18)
        lev_collateral_amount = int(max_b / avg_rate)
        max_b = leverage_zap_1inch.max_borrowable(
            controller.address, user_collateral_amount, lev_collateral_amount, N, p_avg
        )
        max_lev = max_b / avg_rate / collateral_decimals

        return max_b, lev_collateral_amount, max_lev

    @pytest.mark.parametrize('N', (4, 15, 50))
    def test_max_borrowable(
        self,
        collateral,
        stablecoin,
        controller,
        user_collateral_amount,
        leverage_zap_1inch,
        router_api_1inch,
        N
    ):
        max_b, max_c, max_lev = self.get_max_borrowable(
            collateral,
            stablecoin,
            controller,
            user_collateral_amount,
            leverage_zap_1inch,
            router_api_1inch,
            N,
        )

        assert max_b > 0
        assert max_c > 0

        if N == 4:
            assert max_lev > 5
        elif N == 15:
            assert max_lev > 3
        elif N == 50:
            assert max_lev > 1.5

    def test_max_borrowable_create_loan(
        self,
        collateral,
        stablecoin,
        controller,
        user_collateral_amount,
        leverage_zap_1inch,
        router_api_1inch,
    ):
        N = 4
        max_b, max_c, max_lev = self.get_max_borrowable(
            collateral,
            stablecoin,
            controller,
            user_collateral_amount,
            leverage_zap_1inch,
            router_api_1inch,
            N,
        )
        calldata = router_api_1inch.get_calldata(
            collateral.address, stablecoin.address, max_b, leverage_zap_1inch.address
        )

        controller.create_loan_extended(
            user_collateral_amount,
            max_b,
            N,
            leverage_zap_1inch.address,
            [0, user_collateral_amount, max_b, 0, 0, 0],
            bytes.fromhex(calldata[2:]),
        )
