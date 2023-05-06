import pytest

from ape import Contract


def test_address_provider_entry(stableswap_factory, address_provider):
    
    address_provider = Contract("0x0000000022D53366457F9d5E68Ec105046FC4383")
    
    assert address_provider.get_address(pytest.STABLESWAP_FACTORY_ADDRESS_PROVIDER_ID) == stableswap_factory.address
    
    if pytest.new_id_created:
        assert address_provider.max_id() == pytest.max_id_before + 1
    else:
        assert address_provider.max_id() == pytest.max_id_before
