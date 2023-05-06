import pytest


_0x0 = pytest.ZERO_ADDRESS


def test_factory_handler_added(metaregistry, stableswap_factory, factory_handler):
    assert metaregistry.get_base_registry(stableswap_factory) == factory_handler.address


def test_stableswap_pools_inserted(metaregistry, rtokens_pools):
    
    for pool_address in rtokens_pools:
        assert metaregistry.is_registered(pool_address)
        assert metaregistry.get_pool_from_lp_token(pool_address) == pool_address
    
    for token_address in pytest.rtokens.values():
        pool_addr = metaregistry.find_pool_for_coins(pytest.stablecoin, token_address, 0)
        assert pool_addr != _0x0
        assert pool_addr in rtokens_pools
