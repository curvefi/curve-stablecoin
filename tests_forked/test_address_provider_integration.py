import pytest

from ape import Contract


def test_address_provider_entry(stableswap_factory, address_provider):
    
    address_provider = Contract("0x0000000022D53366457F9d5E68Ec105046FC4383")
    
    assert address_provider.get_address(pytest.STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID) == stableswap_factory.address
    
    if pytest.new_id_created:
        assert address_provider.max_id() == pytest.max_id_before + 1
    else:
        assert address_provider.max_id() == pytest.max_id_before


def test_factory_handler_added(metaregistry, stableswap_factory, factory_handler):
    assert metaregistry.get_base_registry(stableswap_factory) == factory_handler.address


def test_stableswap_pools_inserted(metaregistry, rtokens_pools):
    
    for pool_address in rtokens_pools:
        assert metaregistry.is_registered(pool_address)
        assert metaregistry.get_pool_from_lp_token(pool_address) == pool_address
    
    for token_address in pytest.rtokens.values():
        pool_addr = metaregistry.find_pool_for_coins(pytest.stablecoin, token_address, 0)
        assert pool_addr != pytest.ZERO_ADDRESS
        assert pool_addr in rtokens_pools
