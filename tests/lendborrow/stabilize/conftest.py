import boa
import pytest
from ...conftest import approx

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
BASE_AMOUNT = 10**6


# Accounts
@pytest.fixture(scope="module")
def receiver(accounts):
    return accounts[1]


@pytest.fixture(scope="module")
def peg_keeper_updater(accounts):
    return accounts[2]


@pytest.fixture(scope="module")
def alice(accounts):
    return accounts[3]


@pytest.fixture(scope="module")
def bob(accounts):
    return accounts[4]


@pytest.fixture(scope="module")
def stablecoin_a(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "USDa", "USDa", 6)


@pytest.fixture(scope="module")
def stablecoin_b(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/ERC20Mock.vy', "USDb", "USDb", 18)


@pytest.fixture(scope="module")
def swap_impl(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/Stableswap.vy')


@pytest.fixture(scope="module")
def swap_deployer(swap_impl, admin):
    with boa.env.prank(admin):
        deployer = boa.load('contracts/testing/SwapFactory.vy', swap_impl.address)
        return deployer


@pytest.fixture(scope="module")
def unsafe_factory(controller_factory, stablecoin, admin, accounts):
    with boa.env.anchor():
        with boa.env.prank(admin):
            # Give admin ability to mint coins for testing (don't do that at home!)
            controller_factory.set_debt_ceiling(admin, 10**6 * 10**18)
        yield controller_factory


@pytest.fixture(scope="module")
def stableswap_a(unsafe_factory, swap_deployer, swap_impl, stablecoin, stablecoin_a, admin):
    with boa.env.prank(admin):
        addr = swap_deployer.deploy(stablecoin_a, stablecoin)
        swap = swap_impl.deployer.at(addr)
        return swap


@pytest.fixture(scope="module")
def stableswap_b(unsafe_factory, swap_deployer, swap_impl, stablecoin, stablecoin_b, admin):
    with boa.env.prank(admin):
        addr = swap_deployer.deploy(stablecoin_b, stablecoin)
        swap = swap_impl.deployer.at(addr)
        return swap


@pytest.fixture(scope="module")
def swaps(stableswap_a, stableswap_b):
    return [stableswap_a, stableswap_b]


@pytest.fixture(scope="module")
def redeemable_tokens(stablecoin_a, stablecoin_b):
    return [stablecoin_a, stablecoin_b]


@pytest.fixture(scope="module")
def price_aggregator(stablecoin, stableswap_a, stableswap_b, admin):
    with boa.env.prank(admin):
        agg = boa.load('contracts/price_oracles/AggregateStablePrice.vy', stablecoin.address, 10**15, admin)
        agg.add_price_pair(stableswap_a.address)
        agg.add_price_pair(stableswap_b.address)
        return agg


@pytest.fixture(scope="module")
def dummy_tricrypto(stablecoin_a, admin):
    with boa.env.prank(admin):
        pool = boa.load('contracts/testing/TricryptoMock.vy',
                        [stablecoin_a.address,
                         "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                         "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599"])
        pool.set_price(0, 3000 * 10**18)
        pool.set_price(1, 20000 * 10**18)
        return pool


@pytest.fixture(scope="module")
def agg(stablecoin, stablecoin_a, stablecoin_b, stableswap_a, stableswap_b, price_aggregator, admin):
    with boa.env.anchor():
        with boa.env.prank(admin):
            stablecoin_a._mint_for_testing(admin, 500000 * 10**6)
            stablecoin_b._mint_for_testing(admin, 500000 * 10**18)

            stablecoin_a.approve(stableswap_a.address, 2**256-1)
            stablecoin.approve(stableswap_a.address, 2**256-1)
            stablecoin_b.approve(stableswap_b.address, 2**256-1)
            stablecoin.approve(stableswap_b.address, 2**256-1)

            stableswap_a.add_liquidity([500000 * 10**6, 500000 * 10**18], 0)
            stableswap_b.add_liquidity([500000 * 10**18, 500000 * 10**18], 0)
        yield price_aggregator


@pytest.fixture(scope="module")
def crypto_agg(dummy_tricrypto, agg, stableswap_a, admin):
    with boa.env.prank(admin):
        crypto_agg = boa.load(
            'contracts/price_oracles/CryptoWithStablePrice.vy',
            dummy_tricrypto.address,
            0,
            stableswap_a,
            agg,
            5000
        )
        crypto_agg.price_w()
        return crypto_agg


@pytest.fixture(scope="module")
def crypto_agg_with_external_oracle(dummy_tricrypto, agg, stableswap_a, chainlink_price_oracle, admin):
    with boa.env.prank(admin):
        crypto_agg = boa.load(
            'contracts/price_oracles/CryptoWithStablePriceAndChainlink.vy',
            dummy_tricrypto.address,
            0,
            stableswap_a,
            agg,
            chainlink_price_oracle.address,
            5000,
            1
        )
        crypto_agg.price_w()
        return crypto_agg


@pytest.fixture(scope="module")
def peg_keepers(stablecoin_a, stablecoin_b, stableswap_a, stableswap_b, controller_factory, agg, admin, receiver):
    pks = []
    with boa.env.prank(admin):
        for (coin, pool) in [(stablecoin_a, stableswap_a), (stablecoin_b, stableswap_b)]:
            pks.append(
                    boa.load(
                        'contracts/stabilizer/PegKeeper.vy',
                        pool.address, 1, receiver, 2 * 10**4,
                        controller_factory.address, agg.address, admin)
            )
    return pks


@pytest.fixture(scope="module")
def agg_monetary_policy(peg_keepers, agg, controller_factory, admin):
    with boa.env.prank(admin):
        mp = boa.load(
                'contracts/mpolicies/AggMonetaryPolicy.vy',
                admin,
                agg.address,
                controller_factory.address,
                [p.address for p in peg_keepers] + [ZERO_ADDRESS] * 3,
                0,  # Rate
                2 * 10**16,  # Sigma 2%
                5 * 10**16)  # Target debt fraction 5%
        mp.rate()
        return mp


@pytest.fixture(scope="module")
def market_agg(controller_factory, collateral_token, agg_monetary_policy, crypto_agg, peg_keepers, admin):
    with boa.env.prank(admin):
        controller_factory.add_market(
            collateral_token.address, 100, 10**16, 0,
            crypto_agg.address,
            agg_monetary_policy.address, 5 * 10**16, 2 * 10**16,
            10**8 * 10**18)
        for pk in peg_keepers:
            controller_factory.set_debt_ceiling(pk.address, 10**7 * 10**18)
        return controller_factory


@pytest.fixture(scope="module")
def market_amm_agg(market, collateral_token, stablecoin, amm_impl, amm_interface, accounts):
    amm = amm_interface.at(market.get_amm(collateral_token.address))
    for acc in accounts:
        with boa.env.prank(acc):
            collateral_token.approve(amm.address, 2**256-1)
            stablecoin.approve(amm.address, 2**256-1)
    return amm


@pytest.fixture(scope="module")
def market_controller_agg(market_agg, stablecoin, collateral_token, controller_impl, controller_interface, controller_factory, accounts):
    controller = controller_interface.at(market_agg.get_controller(collateral_token.address))
    for acc in accounts:
        with boa.env.prank(acc):
            collateral_token.approve(controller.address, 2**256-1)
            stablecoin.approve(controller.address, 2**256-1)
    return controller


@pytest.fixture(scope="module")
def initial_amounts(redeemable_tokens, stablecoin):
    stablecoin_amount = BASE_AMOUNT * 10**stablecoin.decimals()
    return [(BASE_AMOUNT * 10**redeemable.decimals(), stablecoin_amount) for redeemable in redeemable_tokens]


@pytest.fixture(scope="module")
def _mint(stablecoin, collateral_token, market_controller_agg):
    def f(acct, coins, amounts):
        with boa.env.prank(acct):
            for coin, amount in zip(coins, amounts):
                if amount > 0:
                    if coin == stablecoin:
                        collateral_amount = amount * 50 // 3000
                        collateral_token._mint_for_testing(acct, collateral_amount)
                        if market_controller_agg.debt(acct) == 0:
                            collateral_token.approve(market_controller_agg.address, 2**256 - 1)
                            market_controller_agg.create_loan(collateral_amount, amount, 5)
                        else:
                            market_controller_agg.borrow_more(collateral_amount, amount)
                    else:
                        coin._mint_for_testing(acct, amount)
    return f


@pytest.fixture(scope="module")
def add_initial_liquidity(
        initial_amounts, stablecoin, redeemable_tokens, swaps, collateral_token, market_controller_agg, alice, _mint):
    with boa.env.prank(alice):
        for (amount_r, amount_s), redeemable, pool in zip(initial_amounts, redeemable_tokens, swaps):
            _mint(alice, [redeemable, stablecoin], [amount_r, amount_s])
            stablecoin.approve(pool.address, 2**256 - 1)
            redeemable.approve(pool.address, 2**256 - 1)
            pool.add_liquidity([amount_r, amount_s], 0)


@pytest.fixture(scope="module")
def provide_token_to_peg_keepers_no_sleep(initial_amounts, swaps, peg_keepers, redeemable_tokens, alice, peg_keeper_updater):
    for (amount_r, amount_s), swap, pk, rtoken in zip(initial_amounts, swaps, peg_keepers, redeemable_tokens):
        with boa.env.prank(alice):
            # Mint necessary amount of redeemable token
            rtoken.approve(pk.address, 2**256 - 1)
            amount = amount_r * 5
            rtoken._mint_for_testing(alice, amount)

            # Add redeemable token's liquidity to the stableswap pool
            swap.add_liquidity([amount, 0], 0)

        with boa.env.prank(peg_keeper_updater):
            pk.update()

        with boa.env.prank(alice):
            rtoken_mul = 10 ** (18 - rtoken.decimals())
            remove_amount = (swap.balances(0) * rtoken_mul - swap.balances(1)) // rtoken_mul
            swap.remove_liquidity_imbalance([remove_amount, 0], 2**256 - 1)
            assert approx(swap.balances(0), swap.balances(1) // rtoken_mul, 1e-6)


@pytest.fixture(scope="module")
def provide_token_to_peg_keepers(provide_token_to_peg_keepers_no_sleep):
    boa.env.time_travel(15 * 60)


@pytest.fixture(scope="module")
def imbalance_pool(
        initial_amounts, redeemable_tokens, stablecoin, collateral_token, market_controller_agg, alice, _mint):
    def _inner(swap, i, amount=None, add_diff=False):
        with boa.env.prank(alice):
            rtoken, initial = [(r, i) for r, i in zip(redeemable_tokens, initial_amounts) if r.address == swap.coins(0)][0]
            token_mul = [10 ** (18 - rtoken.decimals()), 1]
            amounts = [0, 0]
            if add_diff:
                amount += (swap.balances(1 - i) * token_mul[1 - i] - swap.balances(i) * token_mul[i]) // token_mul[i]
            amounts[i] = amount or initial[i] // 3
            _mint(alice, [rtoken, stablecoin], amounts)
            swap.add_liquidity(amounts, 0)

    return _inner


@pytest.fixture(scope="module")
def imbalance_pools(
        swaps, initial_amounts, redeemable_tokens, stablecoin, collateral_token, market_controller_agg, alice, _mint):
    def _inner(i, amount=None, add_diff=False):
        with boa.env.prank(alice):
            for initial, swap, rtoken in zip(initial_amounts, swaps, redeemable_tokens):
                token_mul = [10 ** (18 - rtoken.decimals()), 1]
                amounts = [0, 0]
                if add_diff:
                    amount += (swap.balances(1 - i) * token_mul[1 - i] - swap.balances(i) * token_mul[i]) // token_mul[i]
                amounts[i] = amount or initial[i] // 3
                _mint(alice, [rtoken, stablecoin], amounts)
                swap.add_liquidity(amounts, 0)

    return _inner


@pytest.fixture(scope="module")
def mint_bob(bob, stablecoin, redeemable_tokens, swaps, initial_amounts, _mint):
    for swap, rtoken, amounts in zip(swaps, redeemable_tokens, initial_amounts):
        _mint(bob, [rtoken, stablecoin], amounts)
        with boa.env.prank(bob):
            rtoken.approve(swap, 2**256 - 1)
            stablecoin.approve(swap, 2**256 - 1)


@pytest.fixture(scope="module")
def mint_alice(alice, stablecoin, redeemable_tokens, swaps, initial_amounts, _mint):
    for swap, rtoken, amounts in zip(swaps, redeemable_tokens, initial_amounts):
        _mint(alice, [rtoken, stablecoin], amounts)
        with boa.env.prank(alice):
            rtoken.approve(swap, 2**256 - 1)
            stablecoin.approve(swap, 2**256 - 1)


@pytest.fixture(scope="module")
def chainlink_price_oracle(admin):
    return boa.load('contracts/testing/ChainlinkAggregatorMock.vy', 8, admin, 1000)
