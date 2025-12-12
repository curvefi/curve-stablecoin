import boa
from tests.utils.deployers import LP_ORACLE_STABLE_DEPLOYER, LP_ORACLE_CRYPTO_DEPLOYER
from tests.utils.constants import ZERO_ADDRESS


def test_lp_oracle_stable_factory(
    lp_oracle_factory,
    proxy_factory,
    get_stable_swap,
    stable_swap_no_argument,
    coin0_oracle,
    broken_contract,
    admin,
):
    with boa.reverts():
        lp_oracle_factory.deploy_oracle(broken_contract, coin0_oracle)
    with boa.reverts():
        lp_oracle_factory.deploy_oracle(stable_swap_no_argument, broken_contract)
    with boa.reverts():
        lp_oracle_factory.deploy_oracle(get_stable_swap(1), coin0_oracle)

    for N in range(1, 9):  # 1 is for NO_ARGUMENT
        stable_swap = get_stable_swap(N) if N > 1 else stable_swap_no_argument

        if N == 1:
            with boa.env.anchor():
                stable_swap.set_price(0, sender=admin)
                with boa.reverts():
                    lp_oracle_factory.deploy_oracle(stable_swap, coin0_oracle)
        else:
            for i in range(N - 1):
                with boa.env.anchor():
                    stable_swap.set_price(i, 0, sender=admin)
                    with boa.reverts():
                        lp_oracle_factory.deploy_oracle(stable_swap, coin0_oracle)

        with boa.env.anchor():
            coin0_oracle.set_price(0, sender=admin)
            with boa.reverts():
                lp_oracle_factory.deploy_oracle(stable_swap, coin0_oracle)

        with boa.env.anchor():
            oracle, proxy = lp_oracle_factory.deploy_oracle(
                stable_swap, coin0_oracle, False
            )
            oracle = LP_ORACLE_STABLE_DEPLOYER.at(oracle)
            assert oracle.address == lp_oracle_factory.get_oracle(
                stable_swap, coin0_oracle
            )
            assert proxy == ZERO_ADDRESS
            assert oracle.POOL() == stable_swap.address
            assert (
                oracle.price()
                == _get_lp_stable_price(stable_swap) * coin0_oracle.price() // 10**18
            )
            assert (
                oracle.price_w()
                == _get_lp_stable_price(stable_swap) * coin0_oracle.price_w() // 10**18
            )

        oracle, proxy = lp_oracle_factory.deploy_oracle(stable_swap, coin0_oracle)
        oracle = LP_ORACLE_STABLE_DEPLOYER.at(oracle)
        assert oracle.address == lp_oracle_factory.get_oracle(stable_swap, coin0_oracle)
        assert proxy == proxy_factory.get_proxy(oracle)
        assert oracle.POOL() == stable_swap.address
        assert (
            oracle.price()
            == _get_lp_stable_price(stable_swap) * coin0_oracle.price() // 10**18
        )
        assert (
            oracle.price_w()
            == _get_lp_stable_price(stable_swap) * coin0_oracle.price_w() // 10**18
        )

        with boa.reverts("Oracle already exists"):
            lp_oracle_factory.deploy_oracle(stable_swap, coin0_oracle)


def test_lp_oracle_crypto_factory(
    lp_oracle_factory, proxy_factory, crypto_swap, coin0_oracle, broken_contract, admin
):
    with boa.reverts():
        lp_oracle_factory.deploy_oracle(broken_contract, coin0_oracle)
    with boa.reverts():
        lp_oracle_factory.deploy_oracle(crypto_swap, broken_contract)

    with boa.env.anchor():
        crypto_swap.set_lp_price(0, sender=admin)
        with boa.reverts():
            lp_oracle_factory.deploy_oracle(crypto_swap, coin0_oracle)

    with boa.env.anchor():
        coin0_oracle.set_price(0, sender=admin)
        with boa.reverts():
            lp_oracle_factory.deploy_oracle(crypto_swap, coin0_oracle)

    with boa.env.anchor():
        oracle, proxy = lp_oracle_factory.deploy_oracle(
            crypto_swap, coin0_oracle, False
        )
        oracle = LP_ORACLE_CRYPTO_DEPLOYER.at(oracle)
        assert oracle.address == lp_oracle_factory.get_oracle(crypto_swap, coin0_oracle)
        assert proxy == ZERO_ADDRESS
        assert oracle.POOL() == crypto_swap.address
        assert oracle.price() == crypto_swap.lp_price() * coin0_oracle.price() // 10**18
        assert (
            oracle.price_w()
            == crypto_swap.lp_price() * coin0_oracle.price_w() // 10**18
        )

    oracle, proxy = lp_oracle_factory.deploy_oracle(crypto_swap, coin0_oracle)
    oracle = LP_ORACLE_CRYPTO_DEPLOYER.at(oracle)
    assert oracle.address == lp_oracle_factory.get_oracle(crypto_swap, coin0_oracle)
    assert proxy == proxy_factory.get_proxy(oracle)
    assert oracle.POOL() == crypto_swap.address
    assert oracle.price() == crypto_swap.lp_price() * coin0_oracle.price() // 10**18
    assert oracle.price_w() == crypto_swap.lp_price() * coin0_oracle.price_w() // 10**18

    with boa.reverts("Oracle already exists"):
        lp_oracle_factory.deploy_oracle(crypto_swap, coin0_oracle)


def _get_lp_stable_price(stable_swap):
    prices = [10**18]
    for i in range(7):
        try:
            prices.append(stable_swap.price(i))
        except:
            break

    return min(prices)
