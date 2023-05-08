import pytest
from ape import accounts as ape_accounts, Contract, exceptions
from .utils import mint_tokens_for_testing


class TestLendAndSwaps:
    @pytest.fixture()
    def factory_with_market(self, forked_admin, controller_factory, weth, price_oracle_with_chainlink, policy):
        controller_factory.add_market(
            weth,
            100,
            10**16,
            0,
            price_oracle_with_chainlink,
            policy,
            5 * 10**16,
            2 * 10**16,
            4 * pytest.initial_pool_coin_balance * 10**18,
            sender=forked_admin,
        )

    @pytest.fixture()
    def stablecoin_lend(self, project, forked_user, controller_factory, factory_with_market, weth, stablecoin):
        with ape_accounts.use_sender(forked_user):
            controller = project.Controller.at(controller_factory.controllers(0))
            weth.approve(controller.address, 2**256 - 1)
            weth_amount = pytest.initial_eth_balance * 10**18
            controller.create_loan(
                2 * weth_amount, 4 * pytest.initial_pool_coin_balance * 10**18, 30, value=weth_amount
            )

    def test_create_loan_works(self, project, forked_user, controller_factory, weth, stablecoin, factory_with_market):
        with ape_accounts.use_sender(forked_user):
            controller = project.Controller.at(controller_factory.controllers(0))
            weth.approve(controller.address, 2**256 - 1)
            weth_amount = pytest.initial_eth_balance * 10**18
            controller.create_loan(
                2 * weth_amount, 4 * pytest.initial_pool_coin_balance * 10**18, 30, value=weth_amount
            )

    # not enough collateral and not enough debt ceiling for controller
    @pytest.mark.parametrize(
        ("weth_multiplier", "coin_multiplier", "error_msg"),
        ((0.01, 1, "Debt too high"), (1, 1.01, "Transaction failed.")),
    )
    def test_create_loan_fails(
        self,
        project,
        forked_user,
        controller_factory,
        weth,
        stablecoin,
        factory_with_market,
        weth_multiplier: float,
        coin_multiplier: float,
        error_msg: str,
    ):
        with pytest.raises(exceptions.ContractLogicError) as e:
            with ape_accounts.use_sender(forked_user):
                controller = project.Controller.at(controller_factory.controllers(0))
                weth.approve(controller.address, 2**256 - 1)
                weth_amount = int(weth_multiplier * pytest.initial_eth_balance * 10**18)
                controller.create_loan(
                    2 * weth_amount,
                    int(4 * coin_multiplier * pytest.initial_pool_coin_balance * 10**18),
                    30,
                    value=weth_amount,
                )

            assert str(e) == error_msg

    def test_lend_balance(self, forked_user, stablecoin_lend, stablecoin):
        assert stablecoin.balanceOf(forked_user) == 4 * pytest.initial_pool_coin_balance * 10 ** stablecoin.decimals()

    def test_controller(
        self, project, forked_admin, forked_user, controller_factory, stablecoin_lend, stablecoin, weth
    ):
        controller = project.Controller.at(controller_factory.controllers(0))

        with ape_accounts.use_sender(forked_user):
            state = controller.user_state(forked_user)
            assert state[0] == 2 * pytest.initial_eth_balance * 10**18
            assert state[1] == 0
            assert state[2] == controller.debt(forked_user) == 4 * pytest.initial_pool_coin_balance * 10**18
            assert state[3] == 30

            # repay half
            stablecoin.approve(controller.address, 2**256 - 1)
            controller.repay(2 * pytest.initial_pool_coin_balance * 10**18)
            assert stablecoin.balanceOf(forked_user) == 2 * pytest.initial_pool_coin_balance * 10**18

            state = controller.user_state(forked_user)
            assert state[0] == 2 * pytest.initial_eth_balance * 10**18
            assert state[1] == 0
            assert state[2] == controller.debt(forked_user)
            assert (
                2 * pytest.initial_pool_coin_balance * 10**18
                <= state[2]
                <= 2 * pytest.initial_pool_coin_balance * 10**18 * 10001 // 10000
            )
            assert state[3] == 30

            # withdraw eth
            controller.remove_collateral(pytest.initial_eth_balance * 10**18, False)
            assert weth.balanceOf(forked_user) == pytest.initial_eth_balance * 10**18

            state = controller.user_state(forked_user)
            assert state[0] == pytest.initial_eth_balance * 10**18
            assert state[1] == 0
            assert state[2] == controller.debt(forked_user)
            assert (
                2 * pytest.initial_pool_coin_balance * 10**18
                <= state[2]
                <= 2 * pytest.initial_pool_coin_balance * 10**18 * 10001 // 10000
            )
            assert state[3] == 30
            
            controller_factory.set_debt_ceiling(
                controller.address, 20 * pytest.initial_pool_coin_balance * 10**18, sender=forked_admin
            )

            # borrow more without collateral
            max_borrowable = controller.max_borrowable(pytest.initial_eth_balance * 10**18, 30)
            borrow_amount = (max_borrowable - state[2]) // 2  # half of maximum
            controller.borrow_more(0, borrow_amount)
            assert stablecoin.balanceOf(forked_user) == 2 * pytest.initial_pool_coin_balance * 10**18 + borrow_amount

            # borrow more with collateral
            resulting_balance = 2 * pytest.initial_pool_coin_balance * 10**18 + 3 * borrow_amount
            controller.borrow_more(pytest.initial_eth_balance * 10**18, 2 * borrow_amount)
            assert stablecoin.balanceOf(forked_user) == resulting_balance

    @property
    def pool_coin_balance(self):
        return pytest.initial_pool_coin_balance // 2

    @property
    def user_coin_balance(self):
        return pytest.initial_pool_coin_balance - self.pool_coin_balance

    @pytest.fixture()
    def rtokens_pools_with_liquidity(
        self,
        forked_user,
        stablecoin,
        stablecoin_lend,
        rtokens_pools,
    ):
        with ape_accounts.use_sender(forked_user):
            for rtoken_name, rtoken_address in pytest.rtokens.items():
                rtoken = Contract(rtoken_address)
                pool = rtokens_pools[rtoken_name]
                rtoken.approve(pool.address, 2**256 - 1)
                stablecoin.approve(pool.address, 2**256 - 1)

                pool.add_liquidity(
                    [
                        self.pool_coin_balance * 10 ** rtoken.decimals(),
                        self.pool_coin_balance * 10 ** stablecoin.decimals(),
                    ],
                    0,
                )

        return rtokens_pools

    def test_stableswap_liquidity(self, forked_user, rtokens_pools_with_liquidity, stablecoin):
        for pool in rtokens_pools_with_liquidity.values():
            n_coins = 2
            addresses = []
            for n in range(n_coins):
                addr = pool.coins(n)
                addresses.append(addr)

                coin = stablecoin if addr == stablecoin.address else Contract(addr)
                assert pool.balances(n) == self.pool_coin_balance * 10 ** coin.decimals()

            assert stablecoin.address in addresses

    def test_stableswap_swap(self, forked_user, rtokens_pools_with_liquidity, stablecoin):
        with ape_accounts.use_sender(forked_user):
            for pool in rtokens_pools_with_liquidity.values():
                min_value = int(self.pool_coin_balance / 2 * 0.99)  # for a half of liquidity
                decimals_0 = Contract(pool.coins(0)).decimals()
                decimals_1 = stablecoin.decimals()

                assert pool.get_dy(0, 1, self.pool_coin_balance // 2 * 10**decimals_0) >= min_value * 10**decimals_1
                assert pool.get_dy(1, 0, self.pool_coin_balance // 2 * 10**decimals_1) >= min_value * 10**decimals_0

                pool.exchange(0, 1, self.pool_coin_balance // 2 * 10**decimals_0, min_value * 10**decimals_1)
                assert stablecoin.balanceOf(forked_user) >= (min_value + self.user_coin_balance) * 10**decimals_1

    def test_full_repay(
        self, project, accounts, forked_admin, controller_factory, rtokens_pools_with_liquidity, stablecoin
    ):
        user = accounts[3]
        lend_amount = 1000
        mint_tokens_for_testing(project, user, 100_000, lend_amount)

        controller = project.Controller.at(controller_factory.controllers(0))
        controller_factory.set_debt_ceiling(
            controller.address, 8 * pytest.initial_pool_coin_balance * 10**18, sender=forked_admin
        )

        pool = rtokens_pools_with_liquidity["USDT"]
        usdt = Contract("0xdAC17F958D2ee523a2206206994597C13D831ec7")

        with ape_accounts.use_sender(user):
            controller.create_loan(lend_amount * 10**18, 1_000_000 * 10**18, 30, value=lend_amount * 10**18)
            assert controller.loan_exists(user.address)

            # need a little bt more to full repay
            usdt.approve(pool.address, 2**256 - 1)
            pool.exchange(0, 1, 100_000 * 10 ** usdt.decimals(), 1000 * 10**18)

            # full repay
            stablecoin.approve(controller.address, 2**256 - 1)
            controller.repay(stablecoin.balanceOf(user))
            assert not controller.loan_exists(user.address)
