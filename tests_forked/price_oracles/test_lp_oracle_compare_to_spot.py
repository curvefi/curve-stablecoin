import boa
from .settings import EXPLORER_URL, EXPLORER_TOKEN


def test_tricrypto_usdc(stablecoin_aggregator):
    tricrypto_usdc_pool_address = "0x7F86Bf177Dd4F3494b841a37e810A34dD56c829B"
    crvusd_usdc_pool_address = "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E"

    tricrypto_usdc_pool = boa.from_etherscan(tricrypto_usdc_pool_address, "TricryptoUSDC", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)
    crvusd_usdc_pool = boa.from_etherscan(crvusd_usdc_pool_address, "crvUSD/USDC", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)

    usdc_crvusd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRate.vy', [crvusd_usdc_pool_address], [1], [0])  # crvUSD/USDC
    usdc_usd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRateWAgg.vy', [crvusd_usdc_pool_address], [1], [0], stablecoin_aggregator.address)  # USD/USDC
    tricrypto_usdc_crvusd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', tricrypto_usdc_pool_address, usdc_crvusd_oracle.address)  # USDC/LP * crvUSD/USDC
    tricrypto_usdc_usd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', tricrypto_usdc_pool_address, usdc_usd_oracle.address)  # USDC/LP * crvUSD/USDC * USD/crvUSD

    # --- Compare current oracle and spot prices ---

    # Oracle price
    lp_oracle_price_crvusd = tricrypto_usdc_crvusd_lp_oracle.price()
    lp_oracle_price_usd = tricrypto_usdc_usd_lp_oracle.price()

    # Spot price
    usdc_from_lp = tricrypto_usdc_pool.calc_withdraw_one_coin(10 ** 18, 0)
    crvusd_from_lp = crvusd_usdc_pool.get_dy(0, 1, usdc_from_lp)
    lp_spot_price_crvusd = crvusd_from_lp
    lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10 ** 18

    print("LP/crvUSD spot price:", lp_spot_price_crvusd / 10**18, "LP/crvUSD oracle price:", lp_oracle_price_crvusd / 10**18)
    print("LP/USD spot price:", lp_spot_price_usd / 10**18, "LP/USD oracle price:", lp_oracle_price_usd / 10**18)
    print("WBTC/USDC spot price:", tricrypto_usdc_pool.get_dy(1, 0, 10**4) / 10**2, "WBTC/USDC oracle price:", tricrypto_usdc_pool.price_oracle(0) / 10**18)

    assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.005
    assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.005

    boa.env.time_travel(3600)

    # --- DUMP & PUMP ---

    trader = boa.env.generate_address()
    erc_mock = boa.load_partial("contracts/testing/ERC20Mock.vy")
    usdc = erc_mock.at(tricrypto_usdc_pool.coins(0))
    wbtc = erc_mock.at(tricrypto_usdc_pool.coins(1))
    boa.deal(wbtc, trader, 1001 * 10**8)
    initial_wbtc_spot_price = tricrypto_usdc_pool.get_dy(1, 0, 10**4)
    print("USDC pool balance:", usdc.balanceOf(tricrypto_usdc_pool) / 10**6, ", WBTC pool balance:", wbtc.balanceOf(tricrypto_usdc_pool) / 10**8)
    with boa.env.prank(trader):

        # --- DUMP ---

        print("\nTrade 1000 BTC -> POOL -> X USDC")
        wbtc.approve(tricrypto_usdc_pool, 2**256-1)
        tricrypto_usdc_pool.exchange(1, 0, 1000 * 10**8, 0)

        # Align oracle
        for i in range(100):
            boa.env.time_travel(3600)
            tricrypto_usdc_pool.exchange(1, 0, 100, 0)

        # Oracle price
        lp_oracle_price_crvusd = tricrypto_usdc_crvusd_lp_oracle.price_w()
        lp_oracle_price_usd = tricrypto_usdc_usd_lp_oracle.price_w()

        # Spot price
        usdc_from_lp = tricrypto_usdc_pool.calc_withdraw_one_coin(10 ** 18, 0)
        crvusd_from_lp = crvusd_usdc_pool.get_dy(0, 1, usdc_from_lp)
        lp_spot_price_crvusd = crvusd_from_lp
        lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10 ** 18

        print("LP/crvUSD spot price:", lp_spot_price_crvusd / 10 ** 18, "LP/crvUSD oracle price:", lp_oracle_price_crvusd / 10 ** 18)
        print("LP/USD spot price:", lp_spot_price_usd / 10 ** 18, "LP/USD oracle price:", lp_oracle_price_usd / 10 ** 18)
        print("WBTC/USDC spot price:", tricrypto_usdc_pool.get_dy(1, 0, 10 ** 4) / 10 ** 2, "WBTC/USDC oracle price:", tricrypto_usdc_pool.price_oracle(0) / 10 ** 18)

        assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.0005
        assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.0005

        # --- PUMP ---

        print("\ntrade X USDC back -> POOL -> less than 1000 BTC + arbitrage trades")
        usdc.approve(tricrypto_usdc_pool, 2 ** 256 - 1)
        tricrypto_usdc_pool.exchange(0, 1, usdc.balanceOf(trader), 0)

        boa.deal(usdc, trader, 1_000_000 * 10 ** 6)
        while tricrypto_usdc_pool.get_dy(1, 0, 10**4) < initial_wbtc_spot_price * 9999 // 10000:
            tricrypto_usdc_pool.exchange(0, 1, 500 * 10**6, 0)
            boa.env.time_travel(3600)

        print("USDC pool balance:", usdc.balanceOf(tricrypto_usdc_pool) / 10**6, ", WBTC pool balance:", wbtc.balanceOf(tricrypto_usdc_pool) / 10**8)


    # Oracle price
    lp_oracle_price_crvusd = tricrypto_usdc_crvusd_lp_oracle.price()
    lp_oracle_price_usd = tricrypto_usdc_usd_lp_oracle.price()

    # Spot price
    usdc_from_lp = tricrypto_usdc_pool.calc_withdraw_one_coin(10**18, 0)
    crvusd_from_lp = crvusd_usdc_pool.get_dy(0, 1, usdc_from_lp)
    lp_spot_price_crvusd = crvusd_from_lp
    lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

    print("LP/crvUSD spot price:", lp_spot_price_crvusd / 10**18, "LP/crvUSD oracle price:", lp_oracle_price_crvusd / 10**18)
    print("LP/USD spot price:", lp_spot_price_usd / 10**18, "LP/USD oracle price:", lp_oracle_price_usd / 10**18)
    print("WBTC/USDC spot price:", tricrypto_usdc_pool.get_dy(1, 0, 10**4) / 10**2, "WBTC/USDC oracle price:", tricrypto_usdc_pool.price_oracle(0) / 10**18)

    assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.0005
    assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.0005

    raise Exception("Success")


def test_tricrypto_usdt(stablecoin_aggregator):
    tricrypto_usdt_pool_address = "0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4"
    crvusd_usdt_pool_address = "0x390f3595bCa2Df7d23783dFd126427CCeb997BF4"

    tricrypto_usdt_pool = boa.from_etherscan(tricrypto_usdt_pool_address, "TricryptoUSDT", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)
    crvusd_usdt_pool = boa.from_etherscan(crvusd_usdt_pool_address, "crvUSD/USDT", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)

    usdt_crvusd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRate.vy', [crvusd_usdt_pool_address], [1], [0])  # crvUSD/USDT
    usdt_usd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRateWAgg.vy', [crvusd_usdt_pool_address], [1], [0], stablecoin_aggregator.address)  # USD/USDT
    tricrypto_usdt_crvusd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', tricrypto_usdt_pool_address, usdt_crvusd_oracle.address)  # USDT/LP * crvUSD/USDT
    tricrypto_usdt_usd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', tricrypto_usdt_pool_address, usdt_usd_oracle.address)  # USDT/LP * crvUSD/USDT * USD/crvUSD

    # Oracle price
    lp_oracle_price_crvusd = tricrypto_usdt_crvusd_lp_oracle.price()
    lp_oracle_price_usd = tricrypto_usdt_usd_lp_oracle.price()

    # Spot price
    usdt_from_lp = tricrypto_usdt_pool.calc_withdraw_one_coin(10**18, 0)
    crvusd_from_lp = crvusd_usdt_pool.get_dy(0, 1, usdt_from_lp)
    lp_spot_price_crvusd = crvusd_from_lp
    lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

    assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.005
    assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.005


def test_tricrv(stablecoin_aggregator):
    tricrv_pool_address = "0x4eBdF703948ddCEA3B11f675B4D1Fba9d2414A14"

    tricrypto_usdt_pool = boa.from_etherscan(tricrv_pool_address, "TriCRV", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)

    tricrv_crvusd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', tricrv_pool_address, "0x0000000000000000000000000000000000000000")  # USDT/LP * crvUSD/USDT
    tricrv_usd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', tricrv_pool_address, stablecoin_aggregator.address)  # USDT/LP * crvUSD/USDT * USD/crvUSD

    # Oracle price
    lp_oracle_price_crvusd = tricrv_crvusd_lp_oracle.price()
    lp_oracle_price_usd = tricrv_usd_lp_oracle.price()

    # Spot price
    crvusd_from_lp = tricrypto_usdt_pool.calc_withdraw_one_coin(10**18, 0)
    lp_spot_price_crvusd = crvusd_from_lp
    lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

    assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.005
    assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.005


def test_strategic_reserve(stablecoin_aggregator):
    strategic_reserve_pool_address = "0x4f493B7dE8aAC7d55F71853688b1F7C8F0243C85"
    crvusd_usdc_pool_address = "0x4DEcE678ceceb27446b35C672dC7d61F30bAD69E"

    strategic_reserve_pool = boa.from_etherscan(strategic_reserve_pool_address, "StrategicReserveUSD", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)
    crvusd_usdc_pool = boa.from_etherscan(crvusd_usdc_pool_address, "crvUSD/USDC", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)

    usdc_crvusd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRate.vy', [crvusd_usdc_pool_address], [1], [0])  # crvUSD/USDC
    usdc_usd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRateWAgg.vy', [crvusd_usdc_pool_address], [1], [0], stablecoin_aggregator.address)  # USD/USDC
    strategic_reserve_crvusd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', strategic_reserve_pool_address, usdc_crvusd_oracle.address)  # USDC/LP * crvUSD/USDC
    strategic_reserve_usd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', strategic_reserve_pool_address, usdc_usd_oracle.address)  # USDC/LP * crvUSD/USDC * USD/crvUSD

    # Oracle price
    lp_oracle_price_crvusd = strategic_reserve_crvusd_lp_oracle.price()
    lp_oracle_price_usd = strategic_reserve_usd_lp_oracle.price()

    # Spot price
    usdc_from_lp = strategic_reserve_pool.calc_withdraw_one_coin(10**18, 0)
    crvusd_from_lp = crvusd_usdc_pool.get_dy(0, 1, usdc_from_lp)
    lp_spot_price_crvusd = crvusd_from_lp
    lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

    assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.005
    assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.005


def test_weeth_weth(stablecoin_aggregator):
    weeth_ng_pool_address = "0xDB74dfDD3BB46bE8Ce6C33dC9D82777BCFc3dEd5"
    tricrypto_usdt_pool_address = "0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4"
    crvusd_usdt_pool_address = "0x390f3595bCa2Df7d23783dFd126427CCeb997BF4"

    weeth_ng_pool = boa.from_etherscan(weeth_ng_pool_address, "weETH-ng", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)
    tricrypto_usdt_pool = boa.from_etherscan(tricrypto_usdt_pool_address, "TricryptoUSDT", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)
    crvusd_usdt_pool = boa.from_etherscan(crvusd_usdt_pool_address, "crvUSD/USDT", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)

    usdt_crvusd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRate.vy',
                                  [tricrypto_usdt_pool_address, crvusd_usdt_pool_address], [0, 1], [2, 0])  # crvUSD/ETH
    usdt_usd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRateWAgg.vy',
                               [tricrypto_usdt_pool_address, crvusd_usdt_pool_address], [0, 1], [2, 0], stablecoin_aggregator.address)  # USD/ETH
    tricrypto_usdt_crvusd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', weeth_ng_pool_address, usdt_crvusd_oracle.address)  # ETH/LP * crvUSD/ETH
    tricrypto_usdt_usd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', weeth_ng_pool_address, usdt_usd_oracle.address)  # ETH/LP * crvUSD/ETH * USD/crvUSD

    # Oracle price
    lp_oracle_price_crvusd = tricrypto_usdt_crvusd_lp_oracle.price()
    lp_oracle_price_usd = tricrypto_usdt_usd_lp_oracle.price()

    # Spot price
    eth_from_lp = weeth_ng_pool.calc_withdraw_one_coin(10**18, 0)
    usdt_from_lp = tricrypto_usdt_pool.get_dy(2, 0, eth_from_lp)
    crvusd_from_lp = crvusd_usdt_pool.get_dy(0, 1, usdt_from_lp)
    lp_spot_price_crvusd = crvusd_from_lp
    lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

    assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.006
    assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.006


def test_cvxcrv(stablecoin_aggregator):
    cvxcrv_pool_address = "0x971add32Ea87f10bD192671630be3BE8A11b8623"
    tricrv_pool_address = "0x4eBdF703948ddCEA3B11f675B4D1Fba9d2414A14"

    cvxcrv_pool = boa.from_etherscan(cvxcrv_pool_address, "cvxCRV/CRV", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)
    tricrv_pool = boa.from_etherscan(tricrv_pool_address, "TriCRV", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)

    crv_crvusd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRate.vy', [tricrv_pool_address], [0], [2])  # crvUSD/CRV
    crv_usd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRateWAgg.vy', [tricrv_pool_address], [0], [2], stablecoin_aggregator.address)  # USD/CRV
    cvxcrv_pool_crvusd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', cvxcrv_pool_address, crv_crvusd_oracle)  # CRV/LP * crvUSD/CRV
    cvxcrv_pool_usd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', cvxcrv_pool_address, crv_usd_oracle)  # CRV/LP * crvUSD/CRV * USD/crvUSD

    # Oracle price
    lp_oracle_price_crvusd = cvxcrv_pool_crvusd_lp_oracle.price()
    lp_oracle_price_usd = cvxcrv_pool_usd_lp_oracle.price()

    # Spot price
    crv_from_lp = cvxcrv_pool.calc_withdraw_one_coin(10**18, 0)
    crvusd_from_lp = tricrv_pool.get_dy(2, 0, crv_from_lp)
    lp_spot_price_crvusd = crvusd_from_lp
    lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

    # assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.006
    # assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.006

    trader = boa.env.generate_address()
    erc_mock = boa.load_partial("contracts/testing/ERC20Mock.vy")
    crv = erc_mock.at(cvxcrv_pool.coins(0))
    cvxcrv = erc_mock.at(cvxcrv_pool.coins(1))
    boa.deal(crv, trader, 25_000_000 * 10**18)
    print("CRV pool balance:", crv.balanceOf(cvxcrv_pool) / 10**18, ", cvxCRV pool balance:", cvxcrv.balanceOf(cvxcrv_pool) / 10**18)
    with boa.env.prank(trader):

        # --- DUMP ---

        print("\nTrade 5M CRV -> POOL -> X cvxCRV")
        crv.approve(cvxcrv_pool, 2**256-1)
        cvxcrv_pool.exchange(0, 1, 14_000_000 * 10**18, 0)

        # Align oracle
        for i in range(100):
            boa.env.time_travel(3600)
            cvxcrv_pool.exchange(0, 1, 10**12, 0)

        # Oracle price
        lp_oracle_price_crvusd = cvxcrv_pool_crvusd_lp_oracle.price_w()
        lp_oracle_price_usd = cvxcrv_pool_usd_lp_oracle.price_w()

        # Spot price
        crv_from_lp = cvxcrv_pool.calc_withdraw_one_coin(10 ** 18, 0)
        crvusd_from_lp = tricrv_pool.get_dy(2, 0, crv_from_lp)
        lp_spot_price_crvusd = crvusd_from_lp
        lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10 ** 18

        print("LP/crvUSD spot price:", lp_spot_price_crvusd / 10 ** 18, "LP/crvUSD oracle price:", lp_oracle_price_crvusd / 10 ** 18)
        print("LP/USD spot price:", lp_spot_price_usd / 10 ** 18, "LP/USD oracle price:", lp_oracle_price_usd / 10 ** 18)
        print("cvxCRV/CRV spot price:", cvxcrv_pool.get_dy(1, 0, 10**12) / 10 ** 12, "cvxCRV/CRV oracle price:", cvxcrv_pool.price_oracle() / 10 ** 18)

        assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.0005
        assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.0005

    raise Exception("Success")
