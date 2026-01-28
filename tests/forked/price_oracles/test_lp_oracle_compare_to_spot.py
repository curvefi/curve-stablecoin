import boa


def test_tricrypto_usdc(lp_oracle_factory, stablecoin_aggregator, admin, trader):
    tricrypto_usdc_pool_address = "0x7F86Bf177Dd4F3494b841a37e810A34dD56c829B"
    crvusd_usdc_pool_address = "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E"

    tricrypto_usdc_pool = boa.from_etherscan(
        tricrypto_usdc_pool_address,
        name="TricryptoUSDC",
    )
    crvusd_usdc_pool = boa.from_etherscan(
        crvusd_usdc_pool_address,
        name="crvUSD/USDC",
    )

    usdc_crvusd_oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRate.vy",
        [crvusd_usdc_pool_address],
        [1],
        [0],
    )  # crvUSD/USDC
    usdc_usd_oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRateWAgg.vy",
        [crvusd_usdc_pool_address],
        [1],
        [0],
        stablecoin_aggregator.address,
    )  # USD/USDC
    with boa.env.prank(admin):
        tricrypto_usdc_crvusd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(
                tricrypto_usdc_pool_address, usdc_crvusd_oracle.address
            )[1]
        )  # USDC/LP * crvUSD/USDC
        tricrypto_usdc_usd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(
                tricrypto_usdc_pool_address, usdc_usd_oracle.address
            )[1]
        )  # USDC/LP * crvUSD/USDC * USD/crvUSD

    # --- Compare oracle and spot prices ---

    erc_mock = boa.load_partial("curve_stablecoin/testing/ERC20Mock.vy")
    usdc = erc_mock.at(tricrypto_usdc_pool.coins(0))
    wbtc = erc_mock.at(tricrypto_usdc_pool.coins(1))
    boa.deal(usdc, trader, usdc.balanceOf(tricrypto_usdc_pool) * 10)
    boa.deal(wbtc, trader, wbtc.balanceOf(tricrypto_usdc_pool) * 10)
    initial_wbtc_spot_price = tricrypto_usdc_pool.get_dy(1, 0, 10**4)

    with boa.env.prank(trader):
        usdc.approve(tricrypto_usdc_pool, 2**256 - 1)
        wbtc.approve(tricrypto_usdc_pool, 2**256 - 1)

        prices_to_check = [
            int(p * initial_wbtc_spot_price)
            for p in [
                0.40,
                0.50,
                0.60,
                0.70,
                0.80,
                0.90,
                0.92,
                0.95,
                0.98,
                1.00,
                1.02,
                1.05,
                1.08,
                1.10,
                1.20,
                1.30,
                1.40,
                1.50,
                1.60,
                1.80,
                2.00,
            ]
        ]
        for target_p in prices_to_check:
            while tricrypto_usdc_pool.get_dy(1, 0, 10**4) > target_p:
                tricrypto_usdc_pool.exchange(
                    1, 0, wbtc.balanceOf(tricrypto_usdc_pool) // 500, 0
                )
                boa.env.time_travel(3600)

            while tricrypto_usdc_pool.get_dy(1, 0, 10**4) < target_p:
                tricrypto_usdc_pool.exchange(
                    0, 1, usdc.balanceOf(tricrypto_usdc_pool) // 500, 0
                )
                boa.env.time_travel(3600)

            # Oracle price
            lp_oracle_price_crvusd = tricrypto_usdc_crvusd_lp_oracle.price()
            lp_oracle_price_usd = tricrypto_usdc_usd_lp_oracle.price()

            # Spot price
            usdc_from_lp = tricrypto_usdc_pool.calc_withdraw_one_coin(10**18, 0)
            crvusd_from_lp = crvusd_usdc_pool.get_dy(0, 1, usdc_from_lp)
            lp_spot_price_crvusd = crvusd_from_lp
            lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

            delta = 1e-3
            print(
                "p =",
                target_p / 10**2,
                "delta =",
                abs(lp_spot_price_usd - lp_oracle_price_usd)
                / lp_oracle_price_usd
                * 100,
                "%",
                "<",
                delta * 100,
                "%",
            )
            assert (
                abs(lp_spot_price_crvusd - lp_oracle_price_crvusd)
                / lp_oracle_price_crvusd
                < delta
            )
            assert (
                abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd
                < delta
            )


def test_tricrypto_usdt(lp_oracle_factory, stablecoin_aggregator, admin, trader):
    tricrypto_usdt_pool_address = "0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4"
    crvusd_usdt_pool_address = "0x390f3595bCa2Df7d23783dFd126427CCeb997BF4"

    tricrypto_usdt_pool = boa.from_etherscan(
        tricrypto_usdt_pool_address,
        name="TricryptoUSDT",
    )
    crvusd_usdt_pool = boa.from_etherscan(
        crvusd_usdt_pool_address,
        name="crvUSD/USDT",
    )

    usdt_crvusd_oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRate.vy",
        [crvusd_usdt_pool_address],
        [1],
        [0],
    )  # crvUSD/USDT
    usdt_usd_oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRateWAgg.vy",
        [crvusd_usdt_pool_address],
        [1],
        [0],
        stablecoin_aggregator.address,
    )  # USD/USDT
    with boa.env.prank(admin):
        tricrypto_usdt_crvusd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(
                tricrypto_usdt_pool_address, usdt_crvusd_oracle.address
            )[1]
        )  # USDT/LP * crvUSD/USDT
        tricrypto_usdt_usd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(
                tricrypto_usdt_pool_address, usdt_usd_oracle.address
            )[1]
        )  # USDT/LP * crvUSD/USDT * USD/crvUSD

    # --- Compare oracle and spot prices ---

    # USDT interface is different (does not return bool from 'approve' method, for example)
    usdt = boa.from_etherscan(
        tricrypto_usdt_pool.coins(0),
        name="USDT",
    )
    wbtc = boa.load_partial("curve_stablecoin/testing/ERC20Mock.vy").at(
        tricrypto_usdt_pool.coins(1)
    )
    boa.deal(usdt, trader, usdt.balanceOf(tricrypto_usdt_pool) * 10)
    boa.deal(wbtc, trader, wbtc.balanceOf(tricrypto_usdt_pool) * 10)
    initial_wbtc_spot_price = tricrypto_usdt_pool.get_dy(1, 0, 10**4)

    with boa.env.prank(trader):
        usdt.approve(tricrypto_usdt_pool, 2**256 - 1)
        wbtc.approve(tricrypto_usdt_pool, 2**256 - 1)

        prices_to_check = [
            int(p * initial_wbtc_spot_price)
            for p in [
                0.40,
                0.50,
                0.60,
                0.70,
                0.80,
                0.90,
                0.92,
                0.95,
                0.98,
                1.00,
                1.02,
                1.05,
                1.08,
                1.10,
                1.20,
                1.30,
                1.40,
                1.50,
                1.60,
                1.80,
                2.00,
            ]
        ]
        for target_p in prices_to_check:
            while tricrypto_usdt_pool.get_dy(1, 0, 10**4) > target_p:
                tricrypto_usdt_pool.exchange(
                    1, 0, wbtc.balanceOf(tricrypto_usdt_pool) // 500, 0
                )
                boa.env.time_travel(3600)

            while tricrypto_usdt_pool.get_dy(1, 0, 10**4) < target_p:
                tricrypto_usdt_pool.exchange(
                    0, 1, usdt.balanceOf(tricrypto_usdt_pool) // 500, 0
                )
                boa.env.time_travel(3600)

            # Oracle price
            lp_oracle_price_crvusd = tricrypto_usdt_crvusd_lp_oracle.price()
            lp_oracle_price_usd = tricrypto_usdt_usd_lp_oracle.price()

            # Spot price
            usdt_from_lp = tricrypto_usdt_pool.calc_withdraw_one_coin(10**18, 0)
            crvusd_from_lp = crvusd_usdt_pool.get_dy(0, 1, usdt_from_lp)
            lp_spot_price_crvusd = crvusd_from_lp
            lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

            delta = 6e-3
            print(
                "p =",
                target_p / 10**2,
                "delta =",
                abs(lp_spot_price_usd - lp_oracle_price_usd)
                / lp_oracle_price_usd
                * 100,
                "%",
                "<",
                delta * 100,
                "%",
            )
            assert (
                abs(lp_spot_price_crvusd - lp_oracle_price_crvusd)
                / lp_oracle_price_crvusd
                < delta
            )
            assert (
                abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd
                < delta
            )


def test_tricrv(lp_oracle_factory, stablecoin_aggregator, admin, trader):
    tricrv_pool_address = "0x4eBdF703948ddCEA3B11f675B4D1Fba9d2414A14"

    tricrv_pool = boa.from_etherscan(
        tricrv_pool_address,
        name="TriCRV",
    )
    with boa.env.prank(admin):
        tricrv_crvusd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(
                tricrv_pool_address, "0x0000000000000000000000000000000000000000"
            )[1]
        )  # USDT/LP * crvUSD/USDT
        tricrv_usd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(
                tricrv_pool_address, stablecoin_aggregator.address
            )[1]
        )  # USDT/LP * crvUSD/USDT * USD/crvUSD

    # --- Compare oracle and spot prices ---

    crvusd = boa.load_partial("curve_stablecoin/testing/ERC20Mock.vy").at(
        tricrv_pool.coins(0)
    )
    weth = boa.load_partial("curve_stablecoin/testing/WETH.vy").at(tricrv_pool.coins(1))
    boa.deal(crvusd, trader, crvusd.balanceOf(tricrv_pool) * 10)
    boa.env.set_balance(trader, boa.env.get_balance(tricrv_pool.address) * 10)
    weth.deposit(sender=trader, value=boa.env.get_balance(tricrv_pool.address) * 10)
    initial_weth_spot_price = tricrv_pool.get_dy(1, 0, 10**12)

    with boa.env.prank(trader):
        crvusd.approve(tricrv_pool, 2**256 - 1)
        weth.approve(tricrv_pool, 2**256 - 1)

        prices_to_check = [
            int(p * initial_weth_spot_price)
            for p in [
                0.40,
                0.50,
                0.60,
                0.70,
                0.80,
                0.90,
                0.92,
                0.95,
                0.98,
                1.00,
                1.02,
                1.05,
                1.08,
                1.10,
                1.20,
                1.30,
                1.40,
                1.50,
                1.60,
                1.80,
                2.00,
            ]
        ]
        for target_p in prices_to_check:
            while tricrv_pool.get_dy(1, 0, 10**12) > target_p:
                tricrv_pool.exchange(
                    1, 0, boa.env.get_balance(tricrv_pool.address) // 500, 0
                )
                boa.env.time_travel(3600)

            while tricrv_pool.get_dy(1, 0, 10**12) < target_p:
                tricrv_pool.exchange(0, 1, crvusd.balanceOf(tricrv_pool) // 500, 0)
                boa.env.time_travel(3600)

            # Oracle price
            lp_oracle_price_crvusd = tricrv_crvusd_lp_oracle.price_w()
            lp_oracle_price_usd = tricrv_usd_lp_oracle.price_w()

            # Spot price
            crvusd_from_lp = tricrv_pool.calc_withdraw_one_coin(10**18, 0)
            lp_spot_price_crvusd = crvusd_from_lp
            lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

            delta = 2e-3 if target_p / initial_weth_spot_price < 0.5 else 1e-3
            print(
                "p =",
                target_p / 10**12,
                "delta =",
                abs(lp_spot_price_usd - lp_oracle_price_usd)
                / lp_oracle_price_usd
                * 100,
                "%",
                "<",
                delta * 100,
                "%",
            )
            assert (
                abs(lp_spot_price_crvusd - lp_oracle_price_crvusd)
                / lp_oracle_price_crvusd
                < delta
            )
            assert (
                abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd
                < delta
            )


def test_strategic_reserve(lp_oracle_factory, stablecoin_aggregator, admin, trader):
    strategic_reserve_pool_address = "0x4f493B7dE8aAC7d55F71853688b1F7C8F0243C85"
    crvusd_usdc_pool_address = "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E"

    strategic_reserve_pool = boa.from_etherscan(
        strategic_reserve_pool_address,
        name="StrategicReserveUSD",
    )
    crvusd_usdc_pool = boa.from_etherscan(
        crvusd_usdc_pool_address,
        name="crvUSD/USDC",
    )

    usdc_crvusd_oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRate.vy",
        [crvusd_usdc_pool_address],
        [1],
        [0],
    )  # crvUSD/USDC
    usdc_usd_oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRateWAgg.vy",
        [crvusd_usdc_pool_address],
        [1],
        [0],
        stablecoin_aggregator.address,
    )  # USD/USDC
    with boa.env.prank(admin):
        strategic_reserve_crvusd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(
                strategic_reserve_pool_address, usdc_crvusd_oracle.address
            )[1]
        )  # USDC/LP * crvUSD/USDC
        strategic_reserve_usd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(
                strategic_reserve_pool_address, usdc_usd_oracle.address
            )[1]
        )  # USDC/LP * crvUSD/USDC * USD/crvUSD

    # --- Compare oracle and spot prices ---

    erc_mock = boa.load_partial("curve_stablecoin/testing/ERC20Mock.vy")
    usdc = erc_mock.at(strategic_reserve_pool.coins(0))
    # USDT interface is different (does not return bool from 'approve' method, for example)
    usdt = boa.from_etherscan(
        strategic_reserve_pool.coins(1),
        name="USDT",
    )
    boa.deal(usdc, trader, usdc.balanceOf(strategic_reserve_pool) * 10)
    boa.deal(usdt, trader, usdt.balanceOf(strategic_reserve_pool) * 10)
    with boa.env.prank(trader):
        usdc.approve(strategic_reserve_pool, 2**256 - 1)
        usdt.approve(strategic_reserve_pool, 2**256 - 1)

        prices_to_check = [
            p * 10**16
            for p in [
                40,
                50,
                60,
                70,
                80,
                90,
                92,
                95,
                98,
                100,
                102,
                105,
                108,
                110,
                120,
                130,
                140,
                150,
                160,
                180,
                200,
            ]
        ]
        for target_p in prices_to_check:
            while strategic_reserve_pool.get_p(0) > target_p:
                strategic_reserve_pool.exchange(
                    1, 0, usdt.balanceOf(strategic_reserve_pool) // 500, 0
                )
                boa.env.time_travel(3600)

            while strategic_reserve_pool.get_p(0) < target_p:
                strategic_reserve_pool.exchange(
                    0, 1, usdc.balanceOf(strategic_reserve_pool) // 500, 0
                )
                boa.env.time_travel(3600)

            # Oracle price
            lp_oracle_price_crvusd = strategic_reserve_crvusd_lp_oracle.price()
            lp_oracle_price_usd = strategic_reserve_usd_lp_oracle.price()

            # Spot price
            usdc_from_lp = strategic_reserve_pool.calc_withdraw_one_coin(10**18, 0)
            crvusd_from_lp = crvusd_usdc_pool.get_dy(0, 1, usdc_from_lp)
            lp_spot_price_crvusd = crvusd_from_lp
            lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

            delta = 0.0011 * (1 + 0.15 * (abs(target_p - 10**18) / 10**16))
            print(
                "p =",
                target_p / 10**18,
                "delta =",
                abs(lp_spot_price_usd - lp_oracle_price_usd)
                / lp_oracle_price_usd
                * 100,
                "%",
                "<",
                delta * 100,
                "%",
            )
            assert (
                abs(lp_spot_price_crvusd - lp_oracle_price_crvusd)
                / lp_oracle_price_crvusd
                < delta
            )
            assert (
                abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd
                < delta
            )


def test_weeth_weth(lp_oracle_factory, stablecoin_aggregator, admin, trader):
    weeth_ng_pool_address = "0xDB74dfDD3BB46bE8Ce6C33dC9D82777BCFc3dEd5"
    tricrypto_usdt_pool_address = "0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4"
    crvusd_usdt_pool_address = "0x390f3595bCa2Df7d23783dFd126427CCeb997BF4"

    weeth_ng_pool = boa.from_etherscan(
        weeth_ng_pool_address,
        name="weETH-ng",
    )
    tricrypto_usdt_pool = boa.from_etherscan(
        tricrypto_usdt_pool_address,
        name="TricryptoUSDT",
    )
    crvusd_usdt_pool = boa.from_etherscan(
        crvusd_usdt_pool_address,
        name="crvUSD/USDT",
    )

    usdt_crvusd_oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRate.vy",
        [tricrypto_usdt_pool_address, crvusd_usdt_pool_address],
        [0, 1],
        [2, 0],
    )  # crvUSD/ETH
    usdt_usd_oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRateWAgg.vy",
        [tricrypto_usdt_pool_address, crvusd_usdt_pool_address],
        [0, 1],
        [2, 0],
        stablecoin_aggregator.address,
    )  # USD/ETH
    with boa.env.prank(admin):
        weeth_ng_pool_crvusd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(
                weeth_ng_pool_address, usdt_crvusd_oracle.address
            )[1]
        )  # ETH/LP * crvUSD/ETH
        weeth_ng_pool_usd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(
                weeth_ng_pool_address, usdt_usd_oracle.address
            )[1]
        )  # ETH/LP * crvUSD/ETH * USD/crvUSD

    # --- Compare oracle and spot prices ---

    weth = boa.load_partial("curve_stablecoin/testing/WETH.vy").at(
        weeth_ng_pool.coins(0)
    )
    weeth = boa.load_partial("curve_stablecoin/testing/ERC20Mock.vy").at(
        weeth_ng_pool.coins(1)
    )
    boa.env.set_balance(trader, weth.balanceOf(weeth_ng_pool) * 10)
    weth.deposit(sender=trader, value=weth.balanceOf(weeth_ng_pool) * 10)
    boa.deal(weeth, trader, weeth.balanceOf(weeth_ng_pool) * 10)

    with boa.env.prank(trader):
        weth.approve(weeth_ng_pool, 2**256 - 1)
        weeth.approve(weeth_ng_pool, 2**256 - 1)

        # Align TricryptoUSDT oracle
        weth.approve(tricrypto_usdt_pool, 2**256 - 1)
        for i in range(100):
            tricrypto_usdt_pool.exchange(2, 0, 10**9, 0)
            boa.env.time_travel(3600)

        prices_to_check = [
            p * 10**16
            for p in [
                40,
                50,
                60,
                70,
                80,
                90,
                92,
                95,
                98,
                100,
                102,
                105,
                108,
                110,
                120,
                130,
                140,
                150,
                160,
                180,
                200,
            ]
        ]
        for target_p in prices_to_check:
            while weeth_ng_pool.get_p(0) > target_p:
                weeth_ng_pool.exchange(1, 0, weeth.balanceOf(weeth_ng_pool) // 500, 0)
                boa.env.time_travel(3600)

            while weeth_ng_pool.get_p(0) < target_p:
                weeth_ng_pool.exchange(0, 1, weth.balanceOf(weeth_ng_pool) // 500, 0)
                boa.env.time_travel(3600)

            # Oracle price
            lp_oracle_price_crvusd = weeth_ng_pool_crvusd_lp_oracle.price()
            lp_oracle_price_usd = weeth_ng_pool_usd_lp_oracle.price()

            # Spot price
            eth_from_lp = weeth_ng_pool.calc_withdraw_one_coin(10**15, 0)
            usdt_from_lp = tricrypto_usdt_pool.get_dy(2, 0, eth_from_lp)
            crvusd_from_lp = crvusd_usdt_pool.get_dy(0, 1, usdt_from_lp)
            lp_spot_price_crvusd = crvusd_from_lp * 1000
            lp_spot_price_usd = (
                lp_spot_price_crvusd * stablecoin_aggregator.price() // 10**18
            )

            delta = 0.005 if 70 * 10**16 < target_p < 130 * 10**16 else 0.015
            print(
                "p =",
                target_p / 10**18,
                "delta =",
                abs(lp_spot_price_usd - lp_oracle_price_usd)
                / lp_oracle_price_usd
                * 100,
                "%",
                "<",
                delta * 100,
                "%",
            )
            assert (
                abs(lp_spot_price_crvusd - lp_oracle_price_crvusd)
                / lp_oracle_price_crvusd
                < delta
            )
            assert (
                abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd
                < delta
            )


def test_cvxcrv(lp_oracle_factory, stablecoin_aggregator, admin, trader):
    cvxcrv_pool_address = "0x971add32Ea87f10bD192671630be3BE8A11b8623"
    tricrv_pool_address = "0x4eBdF703948ddCEA3B11f675B4D1Fba9d2414A14"

    cvxcrv_pool = boa.from_etherscan(
        cvxcrv_pool_address,
        name="cvxCRV/CRV",
    )
    tricrv_pool = boa.from_etherscan(
        tricrv_pool_address,
        name="TriCRV",
    )

    crv_crvusd_oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRate.vy",
        [tricrv_pool_address],
        [0],
        [2],
    )  # crvUSD/CRV
    crv_usd_oracle = boa.load(
        "curve_stablecoin/price_oracles/CryptoFromPoolsRateWAgg.vy",
        [tricrv_pool_address],
        [0],
        [2],
        stablecoin_aggregator.address,
    )  # USD/CRV
    with boa.env.prank(admin):
        cvxcrv_pool_crvusd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(cvxcrv_pool_address, crv_crvusd_oracle)[1]
        )  # CRV/LP * crvUSD/CRV
        cvxcrv_pool_usd_lp_oracle = boa.load_partial(
            "curve_stablecoin/price_oracles/proxy/ProxyOracle.vy"
        ).at(
            lp_oracle_factory.deploy_oracle(cvxcrv_pool_address, crv_usd_oracle)[1]
        )  # CRV/LP * crvUSD/CRV * USD/crvUSD

    # --- Compare oracle and spot prices ---

    erc_mock = boa.load_partial("curve_stablecoin/testing/ERC20Mock.vy")
    crv = erc_mock.at(cvxcrv_pool.coins(0))
    cvxcrv = erc_mock.at(cvxcrv_pool.coins(1))
    boa.deal(crv, trader, crv.balanceOf(cvxcrv_pool) * 20)
    boa.deal(cvxcrv, trader, cvxcrv.balanceOf(cvxcrv_pool) * 20)
    with boa.env.prank(trader):
        crv.approve(cvxcrv_pool, 2**256 - 1)
        cvxcrv.approve(cvxcrv_pool, 2**256 - 1)

        prices_to_check = [
            p * 10**16
            for p in [
                40,
                50,
                60,
                70,
                80,
                90,
                92,
                95,
                98,
                100,
                102,
                105,
                108,
                110,
                120,
                130,
                140,
                150,
                160,
                180,
                200,
            ]
        ]
        for target_p in prices_to_check:
            while cvxcrv_pool.get_p() > target_p:
                cvxcrv_pool.exchange(1, 0, cvxcrv.balanceOf(cvxcrv_pool) // 500, 0)
                boa.env.time_travel(3600)

            while cvxcrv_pool.get_p() < target_p:
                cvxcrv_pool.exchange(0, 1, crv.balanceOf(cvxcrv_pool) // 500, 0)
                boa.env.time_travel(3600)

            # Oracle price
            lp_oracle_price_crvusd = cvxcrv_pool_crvusd_lp_oracle.price_w()
            lp_oracle_price_usd = cvxcrv_pool_usd_lp_oracle.price_w()

            # Spot price
            crv_from_lp = cvxcrv_pool.calc_withdraw_one_coin(10**18, 0)
            crvusd_from_lp = tricrv_pool.get_dy(2, 0, crv_from_lp)
            lp_spot_price_crvusd = crvusd_from_lp
            lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

            delta = 0.002 * (1 + 1.3 * (abs(target_p - 10**18) / 10**16))
            print(
                "p =",
                target_p / 10**18,
                "delta =",
                abs(lp_spot_price_usd - lp_oracle_price_usd)
                / lp_oracle_price_usd
                * 100,
                "%",
                "<",
                delta * 100,
                "%",
            )
            assert (
                abs(lp_spot_price_crvusd - lp_oracle_price_crvusd)
                / lp_oracle_price_crvusd
                < delta
            )
            assert (
                abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd
                < delta
            )
