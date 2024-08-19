import boa
import pytest
from itertools import permutations


@pytest.fixture()
def swap2(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/MockSwap2.vy')


@pytest.fixture()
def swap3(admin):
    with boa.env.prank(admin):
        return boa.load('contracts/testing/MockSwap3.vy')


@pytest.mark.parametrize("coin_ids", [[0, 1], [1, 0]] + list(permutations([0, 1, 2])))
def test_oracle(swap2, swap3, coin_ids):
    N = len(coin_ids)
    if N == 2:
        swap = swap2
    else:
        swap = swap3
    borrowed_ix, collateral_ix = coin_ids[:2]
    oracle = boa.load('contracts/price_oracles/CryptoFromPool.vy', swap, N, borrowed_ix, collateral_ix)

    p0 = 0.1
    for p in [1, 10, 100]:
        if N == 2:
            if collateral_ix == 1:
                swap.set_price(int(p * 10**18 / p0))
            else:
                swap.set_price(int(p0 * 10**18 / p))
        elif N == 3:
            prices = [10**18, 10**18]
            if borrowed_ix == 0:
                prices[collateral_ix - 1] = int(p * 10**18 / p0)
            elif collateral_ix == 0:
                prices[borrowed_ix - 1] = int(p0 * 10**18 / p)
            else:
                prices[borrowed_ix - 1] = int(p0 * 10**18)
                prices[collateral_ix - 1] = int(p * 10**18)
            swap.set_price(prices[0], 0)
            swap.set_price(prices[1], 1)

        p_cb = int(p * 10**18 / p0)
        assert oracle.price() == p_cb
