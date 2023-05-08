import pytest


def test_address_provider_entry(stableswap_factory, address_provider):
    
    assert address_provider.get_address(pytest.STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID) == stableswap_factory.address
    assert not pytest.new_id_created  # this branch should never happen on mainnet since 
    assert address_provider.max_id() == pytest.max_id_before


def test_factory_handler_integration(metaregistry, stableswap_factory, factory_handler):
    assert metaregistry.get_base_registry(factory_handler) == stableswap_factory


def test_rtoken_pools_in_metaregistry(metaregistry, rtokens_pools):
    
    for pool_address in rtokens_pools.values():
        assert metaregistry.is_registered(pool_address)
        assert metaregistry.get_pool_from_lp_token(pool_address) == pool_address
    
    for token_address in pytest.rtokens.values():
        pool_addr = metaregistry.find_pool_for_coins(pytest.stablecoin, token_address, 0)
        assert pool_addr != pytest.ZERO_ADDRESS
        assert pool_addr in rtokens_pools.values()
