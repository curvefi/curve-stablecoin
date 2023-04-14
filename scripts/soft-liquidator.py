from time import sleep
from brownie import accounts, network, chain, ZERO_ADDRESS
from brownie import ControllerFactory, Controller, AMM, Stablecoin, WETH, Cryptopool, CurveTokenV5, SoftLiquidator
from brownie import ConstantMonetaryPolicy, DummyPriceOracle
from brownie import ERC20Mock

SHORT_NAME = "crvUSD"
FULL_NAME = "Curve.Fi USD Stablecoin"


def deploy_blueprint(contract, account, txparams):
    txparams = {k: v for k, v in txparams.items() if k != 'from'}
    bytecode = b"\xFE\x71\x00" + bytes.fromhex(contract.bytecode[2:])
    bytecode = b"\x61" + len(bytecode).to_bytes(2, "big") + b"\x3d\x81\x60\x0a\x3d\x39\xf3" + bytecode
    tx = account.transfer(data=bytecode, **txparams)
    return tx.contract_address


def deploy_cryptopool(coins, weth, txparams):
    token = CurveTokenV5.deploy("Curve.fi crvUSD-WETH", "crvusdeth", txparams)

    # Params from STG/USDC (https://curve.fi/#/ethereum/pools/factory-crypto-37)
    A = 400000
    gamma = 72500000000000
    mid_fee = 26000000
    out_fee = 45000000
    allowed_extra_profit = 2000000000000
    fee_gamma = 230000000000000
    adjustment_step = 146000000000000
    admin_fee = 5000000000
    ma_half_time = 600
    initial_price = 2600 * 10**18
    _precisions = (18 - coins[0].decimals()) + (18 - coins[1].decimals()) << 8

    pool = Cryptopool.deploy(weth, txparams)
    pool.initialize(A, gamma, mid_fee, out_fee, allowed_extra_profit, fee_gamma, adjustment_step,
                    admin_fee, ma_half_time, initial_price, token, coins, _precisions, txparams)

    token.set_minter(pool, txparams)

    return pool


def main():
    if network.show_active() == 'mainnet':
        raise NotImplementedError("Mainnet not implemented yet")

    admin = accounts[0]
    fee_receiver = accounts[0]
    user = accounts[1]
    liquidity_provider = accounts[2]
    liquidator = accounts[3]

    weth = WETH.deploy({'from': admin})
    stablecoin = Stablecoin.deploy(FULL_NAME, SHORT_NAME, {'from': admin})
    factory = ControllerFactory.deploy(stablecoin, admin, fee_receiver, weth, {'from': admin})
    controller_impl = deploy_blueprint(Controller, accounts[0], {'from': admin})
    amm_impl = deploy_blueprint(AMM, accounts[0], {'from': admin})

    factory.set_implementations(controller_impl, amm_impl, {'from': admin})
    stablecoin.set_minter(factory, {'from': admin})

    policy = ConstantMonetaryPolicy.deploy(admin, {'from': admin})
    policy.set_rate(0, {'from': admin})  # 0%
    price_oracle = DummyPriceOracle.deploy(admin, 3000 * 10**18, {'from': admin})
    collateral = ERC20Mock.deploy('Collateral WETH', 'WETH', 18, {'from': admin})
    cryptopool = deploy_cryptopool([stablecoin, collateral], weth, {'from': admin})

    factory.add_market(
        collateral, 100, 10**16, 0,
        price_oracle,
        policy, 5 * 10**16, 2 * 10**16,
        10**6 * 10**18,
        {'from': admin})

    amm = AMM.at(factory.get_amm(collateral))
    controller = Controller.at(factory.get_controller(collateral))

    liquidator_contract = SoftLiquidator.deploy(amm, cryptopool, stablecoin, collateral, {'from': admin})

    for user in accounts:
        collateral._mint_for_testing(user, 10**4 * 10**18, {'from': admin})

    collateral.approve(controller, int(1.2 * 10**18), {'from': user})
    controller.create_loan(int(1.2 * 10**18), 3000 * 10**18, 20, {'from': user})

    collateral.approve(controller, 1000 * 10 ** 18, {'from': liquidity_provider})
    controller.create_loan(1000 * 10 ** 18, 300_000 * 10 ** 18, 20, {'from': liquidity_provider})
    stablecoin.approve(cryptopool, 2**256 - 1, {'from': liquidity_provider})
    collateral.approve(cryptopool, 2**256 - 1, {'from': liquidity_provider})
    cryptopool.add_liquidity([234_000 * 10 ** 18, 90 * 10 ** 18], 0, {'from': liquidity_provider})

    print('\n========================')
    print("===== LIQUIDATION  =====")
    print('========================\n')

    user_x_down_initial = amm.get_x_down(user)
    tranche = 10**17  # 0.1 WETH
    collateral.approve(liquidator_contract, 2**256 - 1, {'from': liquidator})

    liquidation_profit_collateral_calc = 0
    liquidation_profit_stablecoin_calc = 0
    while True:
        price = price_oracle.price()

        while True:
            output, crv_usd, crv_usd_done = liquidator_contract.calc_output(tranche, True)
            profit_collateral = output - tranche
            print("\n----------------------\n")
            print(f"Price: {price / 10**18}")
            print(f"Profit collateral: {profit_collateral / 10**18} ETH")

            min_crv_usd = int(crv_usd_done * 0.999)
            min_output = int(output * 0.999)
            if 0 < crv_usd_done < crv_usd:
                _expected_crv_usd = cryptopool.get_dy(1, 0, output)
                _min_crv_usd = int(_expected_crv_usd * 0.999)
                if _min_crv_usd > crv_usd_done:
                    tranche = output
                    min_crv_usd = _min_crv_usd

                    profit_stablecoin = _expected_crv_usd - crv_usd_done
                    liquidation_profit_stablecoin_calc += profit_stablecoin
                    print(f"Profit stablecoin: {profit_stablecoin / 10 ** 18} ETH")
                else:
                    break
            elif profit_collateral < 0:
                break

            print(f"Tranche: {tranche / 10 ** 18} ETH")
            liquidation_profit_collateral_calc += max(profit_collateral, 0)
            liquidator_contract.exchange(tranche, min_crv_usd, min_output, True, {'from': liquidator})

        if controller.user_state(user)[0] == 0:
            break

        price_oracle.set_price(price * 98 // 100, {'from': admin})
        chain.sleep(5 * 60)  # 5 minutes
        chain.mine()
        sleep(2)

    user_state_after_liquidation = controller.user_state(user)
    liquidation_profit_collateral = (collateral.balanceOf(liquidator) - 10**4 * 10**18)
    liquidation_profit_stablecoin = stablecoin.balanceOf(liquidator)

    print('\n========================')
    print("==== DE-LIQUIDATION ====")
    print('========================\n')

    tranche = 10 ** 17  # 0.1 WETH
    deliquidation_profit_collateral_calc = 0
    while True:
        price = price_oracle.price()

        while True:
            if controller.user_state(user)[1] == 0:
                break

            output, crv_usd, collateral_done = liquidator_contract.calc_output(tranche, False)
            profit_collateral = output - collateral_done
            print("\n----------------------\n")
            print(f"Price: {price / 10 ** 18}")
            print(f"Profit collateral: {profit_collateral / 10 ** 18} ETH")
            print(f"Tranche: {tranche / 10 ** 18} ETH")

            if profit_collateral < 0:
                break

            deliquidation_profit_collateral_calc += max(profit_collateral, 0)
            min_crv_usd = int(crv_usd * 0.999)
            min_output = int(output * 0.999)
            liquidator_contract.exchange(tranche, min_crv_usd, min_output, False, {'from': liquidator})

        if controller.user_state(user)[1] == 0:
            break

        price_oracle.set_price(price * 102 // 100, {'from': admin})
        chain.sleep(5 * 60)  # 5 minutes
        chain.mine()
        sleep(2)

    user_state_after_deliquidation = controller.user_state(user)
    deliquidation_profit_collateral = (collateral.balanceOf(liquidator) - liquidation_profit_collateral - 10 ** 4 * 10 ** 18)
    deliquidation_profit_stablecoin = stablecoin.balanceOf(liquidator) - liquidation_profit_stablecoin

    print('\n========================')
    print('======== START =========')
    print('========================\n')
    print('User collateral:                       1.2 ETH')
    print('User stablecoin equivalent (x_down):  ', user_x_down_initial / 10**18, 'crvUSD')

    print('\n========================')
    print("===== LIQUIDATION  =====")
    print('========================\n')
    print('User collateral:                      ', user_state_after_liquidation[0] / 10**18)
    print('User stablecoin:                      ', user_state_after_liquidation[1] / 10**18)
    print('Expected liquidator profit:           ',
          liquidation_profit_collateral_calc / 10**18, "ETH,",
          liquidation_profit_stablecoin_calc / 10**18, 'crvUSD')
    print('Liquidator profit:                    ',
          liquidation_profit_collateral / 10**18, 'ETH,',
          liquidation_profit_stablecoin / 10**18, 'crvUSD')

    print('\n========================')
    print("==== DE-LIQUIDATION ====")
    print('========================\n')
    print('User collateral:                      ', user_state_after_deliquidation[0] / 10 ** 18)
    print('User stablecoin:                      ', user_state_after_deliquidation[1] / 10 ** 18)
    print('Expected de-liquidator profit:        ',
          deliquidation_profit_collateral_calc / 10 ** 18, "ETH,",
          0.0, 'crvUSD')
    print('De-liquidator profit:                 ',
          deliquidation_profit_collateral / 10**18, 'ETH,',
          deliquidation_profit_stablecoin / 10**18, 'crvUSD')
