import pytest
from ape import accounts, Contract


@pytest.fixture(scope="module")
def stablecoin_lend(project, forked_user, controller_factory, factory_with_market, weth):
    with accounts.use_sender(forked_user):
        controller = project.Controller.at(controller_factory.controllers(0))
        weth.approve(controller.address, 2**256 - 1)
        weth_amount = pytest.initial_eth_balance * 10**18
        controller.create_loan(weth_amount, 2 * 4 * pytest.initial_pool_coin_balance * 10**18, 30, value=weth_amount)


@pytest.fixture(scope="module")
def rtokens_pools_with_liquidity(
    forked_user,
    stablecoin,
    stablecoin_lend,
    rtokens_pools,
):
    with accounts.use_sender(forked_user):
        for rtoken_name, rtoken_address in pytest.rtokens.items():
            rtoken = Contract(rtoken_address)
            pool = rtokens_pools[rtoken_name]
            rtoken.approve(pool.address, 2**256 - 1)
            stablecoin.approve(pool.address, 2**256 - 1)

            pool.add_liquidity(
                [
                    pytest.initial_pool_coin_balance * 10**rtoken.decimals(),
                    pytest.initial_pool_coin_balance * 10**stablecoin.decimals(),
                ],
                0,
            )

    return rtokens_pools
