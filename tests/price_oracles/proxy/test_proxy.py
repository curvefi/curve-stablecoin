import boa
from tests.utils.deployers import PROXY_ORACLE_DEPLOYER
from tests.utils.constants import ZERO_ADDRESS


def test_proxy(proxy_factory, get_price_oracle, user, admin, broken_price_oracle):
    zero_oracle = get_price_oracle(0)
    oracle1 = get_price_oracle(100 * 10**18)
    with boa.env.prank(user):
        with boa.reverts():
            proxy_factory.deploy_proxy_oracle(broken_price_oracle)
        with boa.reverts("price() call failed"):
            proxy_factory.deploy_proxy_oracle(zero_oracle)
        proxy_address = proxy_factory.deploy_proxy_oracle(oracle1)
    proxy = PROXY_ORACLE_DEPLOYER.at(proxy_address)

    assert proxy.factory() == proxy_factory.address
    assert proxy.oracle() == oracle1.address
    assert proxy_factory.get_proxy(oracle1) == proxy.address
    assert proxy.price() == oracle1.price()
    assert proxy.price_w() == oracle1.price_w()

    # --- Change max deviation ---

    with boa.reverts("Not authorized"):
        proxy.set_max_deviation(500, sender=user)

    with boa.env.prank(admin):
        with boa.reverts("Invalid deviation"):
            proxy.set_max_deviation(0)
        with boa.reverts("Invalid deviation"):
            proxy.set_max_deviation(5001)

        proxy.set_max_deviation(500)

    assert proxy.max_deviation() == 500

    # --- Replace oracle ---

    oracle2 = get_price_oracle(105 * 10 ** 18)
    oracle_deviation_too_high = get_price_oracle(105 * 10 ** 18 + 1)
    with boa.reverts("Not authorized"):
        proxy.set_price_oracle(oracle2, sender=admin)  # Change only through the factory
    with boa.reverts("ownable: caller is not the owner"):
        proxy_factory.replace_oracle(proxy, oracle2, sender=user)

    with boa.env.prank(admin):
        with boa.reverts():
            proxy_factory.replace_oracle(proxy, broken_price_oracle)
        with boa.reverts("price() call failed"):
            proxy_factory.replace_oracle(proxy, zero_oracle)
        with boa.reverts("Price deviation too high"):
            proxy_factory.replace_oracle(proxy, oracle_deviation_too_high)
        with boa.env.anchor():
            proxy_factory.replace_oracle(proxy, oracle_deviation_too_high, True)  # skip deviation check

            assert proxy.oracle() == oracle_deviation_too_high.address
            assert proxy_factory.get_proxy(oracle1) == ZERO_ADDRESS
            assert proxy_factory.get_proxy(oracle_deviation_too_high) == proxy.address
            assert proxy.price() == oracle_deviation_too_high.price()
            assert proxy.price_w() == oracle_deviation_too_high.price_w()

        proxy_factory.replace_oracle(proxy, oracle2)

        assert proxy.oracle() == oracle2.address
        assert proxy_factory.get_proxy(oracle1) == ZERO_ADDRESS
        assert proxy_factory.get_proxy(oracle2) == proxy.address
        assert proxy.price() == oracle2.price()
        assert proxy.price_w() == oracle2.price_w()
