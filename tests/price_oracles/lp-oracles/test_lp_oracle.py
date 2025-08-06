import boa

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _get_lp_stable_price(stable_swap):
    prices = [10**18]
    for i in range(7):
        try:
            prices.append(stable_swap.price(i))
        except:
            break

    return min(prices)


def test_lp_oracle_stable(get_lp_oracle_stable, get_stable_swap, stable_swap_no_argument, coin0_oracle, broken_contract, admin):
    with boa.reverts():
        get_lp_oracle_stable(broken_contract, coin0_oracle)
    with boa.reverts():
        get_lp_oracle_stable(stable_swap_no_argument, broken_contract)
    with boa.reverts("Less than 2 coins"):
        get_lp_oracle_stable(get_stable_swap(1), coin0_oracle)

    for N in range(1, 9):  # 1 is for NO_ARGUMENT
        stable_swap = get_stable_swap(N) if N > 1 else stable_swap_no_argument

        if N == 1:
            with boa.env.anchor():
                stable_swap.set_price(0, sender=admin)
                with boa.reverts("pool.price_oracle() returns 0"):
                    get_lp_oracle_stable(stable_swap, coin0_oracle)
        else:
            for i in range(N-1):
                with boa.env.anchor():
                    stable_swap.set_price(i, 0, sender=admin)
                    with boa.reverts("pool.price_oracle(i) returns 0"):
                        get_lp_oracle_stable(stable_swap, coin0_oracle)

        with boa.env.anchor():
            coin0_oracle.set_price(0, sender=admin)
            with boa.reverts("coin0_oracle.price() returns 0"):
                get_lp_oracle_stable(stable_swap, coin0_oracle)

        oracle = get_lp_oracle_stable(stable_swap, coin0_oracle)
        assert oracle.POOL() == stable_swap.address
        assert oracle.price() == _get_lp_stable_price(stable_swap) * coin0_oracle.price() // 10**18
        assert oracle.price_w() == _get_lp_stable_price(stable_swap) * coin0_oracle.price_w() // 10**18


def test_lp_oracle_crypto(get_lp_oracle_crypto, crypto_swap, coin0_oracle, broken_contract, admin):
    with boa.reverts():
        get_lp_oracle_crypto(broken_contract, coin0_oracle)
    with boa.reverts():
        get_lp_oracle_crypto(crypto_swap, broken_contract)

    with boa.env.anchor():
        crypto_swap.set_lp_price(0, sender=admin)
        with boa.reverts("pool.lp_price() returns 0"):
            get_lp_oracle_crypto(crypto_swap, coin0_oracle)

    with boa.env.anchor():
        coin0_oracle.set_price(0, sender=admin)
        with boa.reverts("coin0_oracle.price() returns 0"):
            get_lp_oracle_crypto(crypto_swap, coin0_oracle)

    oracle = get_lp_oracle_crypto(crypto_swap, coin0_oracle)
    assert oracle.POOL() == crypto_swap.address
    assert oracle.price() == crypto_swap.lp_price() * coin0_oracle.price() // 10**18
    assert oracle.price_w() == crypto_swap.lp_price() * coin0_oracle.price_w() // 10**18
