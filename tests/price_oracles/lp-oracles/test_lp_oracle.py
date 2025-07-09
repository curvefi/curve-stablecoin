import boa

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def test_lp_oracle_crypto(lp_oracle_factory, crypto_swap, coin0_oracle, broken_contract, admin):
    lp_oracle_factory.deploy_oracle(crypto_swap, coin0_oracle)

    with boa.reverts():
        lp_oracle_factory.deploy_oracle(broken_contract, coin0_oracle)
    with boa.reverts():
        lp_oracle_factory.deploy_oracle(crypto_swap, broken_contract)

    with boa.env.anchor():
        crypto_swap.set_lp_price(0, sender=admin)
        with boa.reverts("pool.lp_price() returns 0"):
            lp_oracle_factory.deploy_oracle(crypto_swap, coin0_oracle)

    with boa.env.anchor():
        coin0_oracle.set_price(0, sender=admin)
        with boa.reverts("coin0_oracle.price() returns 0"):
            lp_oracle_factory.deploy_oracle(crypto_swap, coin0_oracle)
