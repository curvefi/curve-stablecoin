from time import sleep
from brownie import accounts, network, ZERO_ADDRESS
from brownie import ControllerFactory, Controller, AMM, Stablecoin, WETH, Cryptopool, CurveTokenV5, HardLiquidator
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
    initial_price = 3000 * 10**18
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
    collateral_token = ERC20Mock.deploy('Collateral WETH', 'WETH', 18, {'from': admin})
    cryptopool = deploy_cryptopool([stablecoin, collateral_token], weth, {'from': admin})

    factory.add_market(
        collateral_token, 100, 10**16, 0,
        price_oracle,
        policy, 5 * 10**16, 2 * 10**16,
        10**6 * 10**18,
        {'from': admin})

    amm = AMM.at(factory.get_amm(collateral_token))
    controller = Controller.at(factory.get_controller(collateral_token))

    liquidator_contract = HardLiquidator.deploy(controller, cryptopool, stablecoin, collateral_token, {'from': admin})

    for user in accounts:
        collateral_token._mint_for_testing(user, 10**4 * 10**18, {'from': admin})

    collateral_token.approve(controller, int(1.2 * 10**18), {'from': user})
    controller.create_loan(int(1.2 * 10**18), 3000 * 10**18, 20, {'from': user})

    collateral_token.approve(controller, 100 * 10 ** 18, {'from': liquidity_provider})
    controller.create_loan(100 * 10 ** 18, 100000 * 10 ** 18, 20, {'from': liquidity_provider})
    stablecoin.approve(cryptopool, 10 ** 30, {'from': liquidity_provider})
    collateral_token.approve(cryptopool, 10 ** 30, {'from': liquidity_provider})
    cryptopool.add_liquidity([90000 * 10 ** 18, 30 * 10 ** 18], 0, {'from': liquidity_provider})

    frac = 17 * 10**16  # 17%
    while True:
        users_to_liquidate = controller.users_to_liquidate()
        price = price_oracle.price()
        print("\n----------------------\n")
        print(f"Price: {price / 10**18}")
        print(f"Users to liquidate: {users_to_liquidate}")
        if len(users_to_liquidate) > 0:
            unhealthy_user, stablecoin_in_amm, collateral_in_amm, debt, health = users_to_liquidate[0]
            tokens_to_liquidate = controller.tokens_to_liquidate(unhealthy_user, frac)

            h = controller.liquidation_discounts(unhealthy_user) / 10**18
            _frac = frac / 10**18
            f_remove = ((1 + h / 2) / (1 + h) * (1 - _frac) + _frac) * _frac  # < frac
            expected = cryptopool.get_dy(1, 0, int(collateral_in_amm * f_remove))

            min_x = int(stablecoin_in_amm * _frac * 0.9999)
            controller.liquidate_extended(
                unhealthy_user,
                min_x,
                frac,
                False,
                liquidator_contract,
                "0x69af9ec200000000000000000000000000000000000000000000000000000000",
                [],
                {'from': liquidator},
            )

            user_state = controller.user_state(user)
            print("\n----------------------\n")
            print(f"User {unhealthy_user} has been liquidated by 17%:\n"
                  f"crvUSD: {stablecoin_in_amm / 10**18}, ETH: {collateral_in_amm / 10**18}, debt: {debt / 10**18} --> "
                  f"crvUSD: {user_state[1] / 10**18}, ETH: {user_state[0] / 10**18}, debt: {user_state[2] / 10**18}\n")
            profit = stablecoin.balanceOf(liquidator)
            print(f"Expected liquidator profit: {(expected - tokens_to_liquidate) / 10**18} crvUSD")
            print(f"Liquidator profit: {profit / 10**18} crvUSD")
            print("\n----------------------\n")
            break

        price_oracle.set_price(price * 97 // 100)
        sleep(1)
