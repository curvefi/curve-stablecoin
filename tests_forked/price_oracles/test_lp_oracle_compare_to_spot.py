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

    # Oracle price
    lp_oracle_price_crvusd = tricrypto_usdc_crvusd_lp_oracle.price()
    lp_oracle_price_usd = tricrypto_usdc_usd_lp_oracle.price()

    # Spot price
    usdc_from_lp = tricrypto_usdc_pool.calc_withdraw_one_coin(10**18, 0)
    crvusd_from_lp = crvusd_usdc_pool.get_dy(0, 1, usdc_from_lp)
    lp_spot_price_crvusd = crvusd_from_lp
    lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

    assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.005
    assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.005


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


def test_weeth_weth(stablecoin_aggregator):
    steth_ng_pool_address = "0xDB74dfDD3BB46bE8Ce6C33dC9D82777BCFc3dEd5"
    tricrypto_usdt_pool_address = "0xf5f5B97624542D72A9E06f04804Bf81baA15e2B4"
    crvusd_usdt_pool_address = "0x390f3595bCa2Df7d23783dFd126427CCeb997BF4"

    steth_ng_pool = boa.from_etherscan(steth_ng_pool_address, "stETH-ng", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)
    tricrypto_usdt_pool = boa.from_etherscan(tricrypto_usdt_pool_address, "TricryptoUSDT", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)
    crvusd_usdt_pool = boa.from_etherscan(crvusd_usdt_pool_address, "crvUSD/USDT", uri=EXPLORER_URL, api_key=EXPLORER_TOKEN)

    usdt_crvusd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRate.vy',
                                  [tricrypto_usdt_pool_address, crvusd_usdt_pool], [0, 1], [2, 0])  # crvUSD/ETH
    usdt_usd_oracle = boa.load('contracts/price_oracles/CryptoFromPoolsRateWAgg.vy',
                               [tricrypto_usdt_pool_address, crvusd_usdt_pool], [0, 1], [2, 0], stablecoin_aggregator.address)  # USD/ETH
    tricrypto_usdt_crvusd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', steth_ng_pool_address, usdt_crvusd_oracle.address)  # ETH/LP * crvUSD/ETH
    tricrypto_usdt_usd_lp_oracle = boa.load('contracts/price_oracles/LPOracle.vy', steth_ng_pool_address, usdt_usd_oracle.address)  # ETH/LP * crvUSD/ETH * USD/crvUSD

    # Oracle price
    lp_oracle_price_crvusd = tricrypto_usdt_crvusd_lp_oracle.price()
    lp_oracle_price_usd = tricrypto_usdt_usd_lp_oracle.price()

    # Spot price
    eth_from_lp = steth_ng_pool.calc_withdraw_one_coin(10**18, 0)
    usdt_from_lp = tricrypto_usdt_pool.get_dy(2, 0, eth_from_lp)
    crvusd_from_lp = crvusd_usdt_pool.get_dy(0, 1, usdt_from_lp)
    lp_spot_price_crvusd = crvusd_from_lp
    lp_spot_price_usd = crvusd_from_lp * stablecoin_aggregator.price() // 10**18

    assert abs(lp_spot_price_crvusd - lp_oracle_price_crvusd) / lp_oracle_price_crvusd < 0.005
    assert abs(lp_spot_price_usd - lp_oracle_price_usd) / lp_oracle_price_usd < 0.005

    print(lp_spot_price_crvusd, lp_oracle_price_crvusd)
    print(lp_spot_price_usd, lp_oracle_price_usd)
