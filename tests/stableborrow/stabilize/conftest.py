import boa
import pytest
from tests.utils.deployers import (
    ERC20_MOCK_DEPLOYER,
    STABLESWAP_DEPLOYER,
    SWAP_FACTORY_DEPLOYER,
    MOCK_RATE_ORACLE_DEPLOYER,
    CURVE_STABLESWAP_FACTORY_NG_DEPLOYER,
    CURVE_STABLESWAP_NG_DEPLOYER,
    CURVE_STABLESWAP_NG_MATH_DEPLOYER,
    CURVE_STABLESWAP_NG_VIEWS_DEPLOYER,
    AGGREGATE_STABLE_PRICE3_DEPLOYER,
    TRICRYPTO_MOCK_DEPLOYER,
    CRYPTO_WITH_STABLE_PRICE_DEPLOYER,
    CRYPTO_WITH_STABLE_PRICE_AND_CHAINLINK_DEPLOYER,
    MOCK_PEG_KEEPER_DEPLOYER,
    PEG_KEEPER_REGULATOR_DEPLOYER,
    PEG_KEEPER_V2_DEPLOYER,
    AGG_MONETARY_POLICY2_DEPLOYER,
    CHAINLINK_AGGREGATOR_MOCK_DEPLOYER
)
from tests.utils.constants import ZERO_ADDRESS
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
def collateral_token(get_collateral_token):
    return get_collateral_token(18)


@pytest.fixture(scope="module")
def stablecoin_a(admin):
    with boa.env.prank(admin):
        return ERC20_MOCK_DEPLOYER.deploy(6)


@pytest.fixture(scope="module")
def stablecoin_b(admin):
    with boa.env.prank(admin):
        return ERC20_MOCK_DEPLOYER.deploy(18)


@pytest.fixture(scope="module")
def swap_impl(admin):
    with boa.env.prank(admin):
        return STABLESWAP_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def swap_deployer(swap_impl, admin):
    with boa.env.prank(admin):
        deployer = SWAP_FACTORY_DEPLOYER.deploy(swap_impl.address)
        return deployer


@pytest.fixture(scope="module")
def rate_oracle(swap_impl, admin):
    return MOCK_RATE_ORACLE_DEPLOYER.deploy()


@pytest.fixture(scope="module")
def swap_impl_ng(admin, swap_deployer, rate_oracle):
    with boa.env.prank(admin):
        # Do not forget `git submodule init` and `git submodule update`
        prefix = "contracts/testing/stableswap-ng/contracts/main"
        factory = CURVE_STABLESWAP_FACTORY_NG_DEPLOYER.deploy(admin, admin)
        swap_deployer.eval(f'self.factory_ng = FactoryNG({factory.address})')
        swap_deployer.eval(f'self.rate_oracle = {rate_oracle.address}')

        impl = CURVE_STABLESWAP_NG_DEPLOYER.deploy_as_blueprint()
        factory.set_pool_implementations(0, impl)

        math = CURVE_STABLESWAP_NG_MATH_DEPLOYER.deploy()
        factory.set_math_implementation(math)

        views = CURVE_STABLESWAP_NG_VIEWS_DEPLOYER.deploy()
        factory.set_views_implementation(views)
        return impl


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
def stableswap_b(unsafe_factory, swap_deployer, swap_impl_ng, stablecoin, stablecoin_b, admin):
    with boa.env.prank(admin):
        addr = swap_deployer.deploy_ng(stablecoin_b, stablecoin)
        swap = swap_impl_ng.deployer.at(addr)
        return swap


@pytest.fixture(scope="module")
def swaps(stableswap_a, stableswap_b):
    return [stableswap_a, stableswap_b]


@pytest.fixture(scope="module")
def set_fee():
    def inner(swap, fee, offpeg_fee_multiplier=None):
        swap.eval(f"self.fee = {fee}")
        if offpeg_fee_multiplier:
            swap.eval(f"self.offpeg_fee_multiplier = {offpeg_fee_multiplier}")
    return inner


@pytest.fixture(scope="module")
def redeemable_tokens(stablecoin_a, stablecoin_b):
    return [stablecoin_a, stablecoin_b]


@pytest.fixture(scope="module")
def price_aggregator(stablecoin, stableswap_a, stableswap_b, admin):
    with boa.env.prank(admin):
        agg = AGGREGATE_STABLE_PRICE3_DEPLOYER.deploy(stablecoin.address, 10**15, admin)
        agg.add_price_pair(stableswap_a.address)
        agg.add_price_pair(stableswap_b.address)
        return agg


@pytest.fixture(scope="module")
def dummy_tricrypto(stablecoin_a, admin):
    with boa.env.prank(admin):
        pool = TRICRYPTO_MOCK_DEPLOYER.deploy(
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
            boa.deal(stablecoin_a, admin, 500000 * 10**6)
            boa.deal(stablecoin_b, admin, 500000 * 10**18)

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
        crypto_agg = CRYPTO_WITH_STABLE_PRICE_DEPLOYER.deploy(
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
        crypto_agg = CRYPTO_WITH_STABLE_PRICE_AND_CHAINLINK_DEPLOYER.deploy(
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
def mock_peg_keepers(stablecoin):
    """ Make Regulator always pass order of prices check """
    return [
        MOCK_PEG_KEEPER_DEPLOYER.deploy(price, stablecoin) for price in [0, 2 ** 256 - 1]
    ]


@pytest.fixture(scope="module")
def reg(agg, stablecoin, mock_peg_keepers, receiver, admin):
    regulator = PEG_KEEPER_REGULATOR_DEPLOYER.deploy(
        stablecoin, agg, receiver, admin, admin
    )
    with boa.env.prank(admin):
        regulator.set_price_deviation(10 ** 20)
        regulator.set_debt_parameters(10 ** 18, 10 ** 18)
        regulator.add_peg_keepers([mock.address for mock in mock_peg_keepers])
    return regulator


@pytest.fixture(scope="module")
def peg_keepers(stablecoin_a, stablecoin_b, stableswap_a, stableswap_b, controller_factory, reg, admin, receiver):
    pks = []
    with boa.env.prank(admin):
        for (coin, pool) in [(stablecoin_a, stableswap_a), (stablecoin_b, stableswap_b)]:
            pks.append(
                    PEG_KEEPER_V2_DEPLOYER.deploy(
                        pool.address, 2 * 10**4,
                        controller_factory.address, reg.address, admin)
            )
        reg.add_peg_keepers([pk.address for pk in pks])
    return pks


@pytest.fixture(scope="module")
def agg_monetary_policy(peg_keepers, agg, controller_factory, admin):
    with boa.env.prank(admin):
        mp = AGG_MONETARY_POLICY2_DEPLOYER.deploy(
                admin,
                agg.address,
                controller_factory.address,
                [p.address for p in peg_keepers] + [ZERO_ADDRESS] * 3,
                0,  # Rate
                2 * 10**16,  # Sigma 2%
                5 * 10**16)  # Target debt fraction 5%
        mp.rate_write()
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
            controller_factory.set_debt_ceiling(pk.address, 10**8 * 10**18)
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
                        boa.deal(collateral_token, acct, collateral_amount)
                        if market_controller_agg.debt(acct) == 0:
                            collateral_token.approve(market_controller_agg.address, 2**256 - 1)
                            market_controller_agg.create_loan(collateral_amount, amount, 5)
                        else:
                            market_controller_agg.borrow_more(collateral_amount, amount)
                    else:
                        boa.deal(coin, acct, amount)
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
            boa.deal(rtoken, alice, amount)

            # Add redeemable token's liquidity to the stableswap pool
            swap.add_liquidity([amount, 0], 0)

        with boa.env.prank(peg_keeper_updater):
            pk.update()

        with boa.env.prank(alice):
            rtoken_mul = 10 ** (18 - rtoken.decimals())
            remove_amount = (swap.balances(0) * rtoken_mul - swap.balances(1)) // rtoken_mul
            swap.remove_liquidity_imbalance([remove_amount, 0], 2**256 - 1)
            assert swap.balances(0) == pytest.approx(swap.balances(1) // rtoken_mul, rel=1e-6)


@pytest.fixture(scope="module")
def provide_token_to_peg_keepers(provide_token_to_peg_keepers_no_sleep):
    boa.env.time_travel(12)


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
    return CHAINLINK_AGGREGATOR_MOCK_DEPLOYER.deploy(8, admin, 1000)
