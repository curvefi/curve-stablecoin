from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, run_state_machine_as_test, initialize, rule, invariant
from boa.vyper.contract import VyperContract
from datetime import timedelta
import boa


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
RATE0 = 634195839  # 2%


class AggMonetaryPolicyCreation(RuleBasedStateMachine):
    digits = st.integers(min_value=6, max_value=18)
    many_digits = st.lists(st.integers(min_value=6, max_value=18), min_size=1, max_size=5)
    deposit_amount = st.floats(min_value=1, max_value=1e9)
    deposit_split = st.floats(min_value=0.5, max_value=1.5)
    pool_number = st.integers(min_value=0, max_value=10000)
    rate = st.integers(min_value=0, max_value=43959106799)
    sigma = st.integers(min_value=10**14, max_value=10**18)
    target_debt_fraction = st.integers(min_value=0, max_value=10**18)

    def __init__(self):
        super().__init__()
        self.controller_factory = self.unsafe_factory
        with boa.env.prank(self.admin):
            # Rug the unsafe factory!
            self.controller_factory.set_debt_ceiling(self.admin, 10**18 * 10**15)
        self.stablecoins = []
        self.one_usd = []
        self.swaps = []
        self.peg_keepers = []
        self.agg = boa.load('contracts/price_oracles/AggregateStablePrice.vy', self.stablecoin.address, 10**15, self.admin)

    @initialize(digits=many_digits)
    def initializer(self, digits):
        for d in digits:
            self.add_stablecoin(d)
            with boa.env.prank(self.admin):
                self.agg.add_price_pair(self.swaps[-1].address)
        self.mp = boa.load(
            'contracts/mpolicies/AggMonetaryPolicy.vy',
            self.admin,
            self.agg.address,
            self.controller_factory.address,
            [p.address for p in self.peg_keepers] + [ZERO_ADDRESS] * (5 - len(digits)),
            RATE0,
            2 * 10**16,  # Sigma 2%
            5 * 10**16)  # Target debt fraction 5%

    def add_stablecoin(self, digits):
        with boa.env.prank(self.admin):
            # Deploy a stablecoin
            fedUSD = boa.load('contracts/testing/ERC20Mock.vy', "USD%s" % digits, "USD%s" % digits, digits)
            # Deploy a swap
            n = self.swap_deployer.n()
            self.swap_deployer.deploy(fedUSD, self.stablecoin)
            addr = self.swap_deployer.pools(n)
            swap = VyperContract(
                self.swap_impl.compiler_data,
                override_address=addr
            )
            fedUSD.approve(swap.address, 2**256 - 1)
            self.stablecoin.approve(swap.address, 2**256 - 1)
            # Deploy a peg keeper
            pk = boa.load('contracts/stabilizer/PegKeeper.vy',
                          swap.address, 1, self.admin, 5 * 10**4,
                          self.controller_factory.address, self.agg.address)
        self.stablecoins.append(fedUSD)
        self.swaps.append(swap)
        self.peg_keepers.append(pk)
        self.one_usd.append(10**digits)

    @rule(d=digits)
    def add_peg_keeper(self, d):
        if len(self.peg_keepers) < 10:
            self.add_stablecoin(d)
            with boa.env.prank(self.admin):
                self.mp.add_peg_keeper(self.peg_keepers[-1].address)

    @rule(_n=pool_number)
    def remove_peg_keeper(self, _n):
        if len(self.peg_keepers) > 0:
            n = _n % len(self.peg_keepers)
            pk = self.peg_keepers.pop(n)
            self.stablecoins.pop(n)
            self.swaps.pop(n)
            self.one_usd.pop(n)
            with boa.env.prank(self.admin):
                self.mp.remove_peg_keeper(pk.address)

    @rule(r=rate)
    def set_rate(self, r):
        with boa.env.prank(self.admin):
            self.mp.set_rate(r)

    @rule(s=sigma)
    def set_sigma(self, s):
        with boa.env.prank(self.admin):
            self.mp.set_sigma(s)

    @rule(f=target_debt_fraction)
    def set_target_debt_fraction(self, f):
        with boa.env.prank(self.admin):
            self.mp.set_target_debt_fraction(f)

    @rule(amount=deposit_amount, split=deposit_split, _n=pool_number)
    def deposit(self, amount, split, _n):
        if len(self.swaps) > 0:
            n = _n % len(self.swaps)
            x = [int(amount * self.one_usd[n]), int(split * amount * 1e18)]
            with boa.env.prank(self.admin):
                self.stablecoins[n]._mint_for_testing(self.admin, 2 * x[0])
                self.swaps[n].add_liquidity(x, 0)
                # Add twice to record the price for MA
                self.swaps[n].add_liquidity(x, 0)
            boa.env.time_travel(86400)

    @invariant()
    def agg_price_readable(self):
        p = self.agg.price() / 1e18
        assert abs(1 - p) < 0.5

    @invariant()
    def rate_readable(self):
        rate = self.mp.rate()
        assert abs((rate - RATE0) / RATE0) < 0.5


def test_agg_mp(unsafe_factory, swap_deployer, swap_impl, stablecoin, admin):
    AggMonetaryPolicyCreation.TestCase.settings = settings(max_examples=30, stateful_step_count=20, deadline=timedelta(seconds=1000))
    for k, v in locals().items():
        setattr(AggMonetaryPolicyCreation, k, v)
    run_state_machine_as_test(AggMonetaryPolicyCreation)
