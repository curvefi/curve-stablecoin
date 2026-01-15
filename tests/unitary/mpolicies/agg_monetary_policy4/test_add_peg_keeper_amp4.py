"""Tests for AggMonetaryPolicy4.add_peg_keeper"""

import boa

from tests.utils import filter_logs
from tests.utils.deployers import MOCK_PEG_KEEPER_DEPLOYER
from tests.utils.constants import ZERO_ADDRESS


def test_default_behavior(admin, price_oracle, mock_factory):
    """Admin can add a peg keeper and AddPegKeeper event is emitted."""
    from tests.utils.deployers import AGG_MONETARY_POLICY4_DEPLOYER

    pk_array = [ZERO_ADDRESS] * 5
    with boa.env.prank(admin):
        mp = AGG_MONETARY_POLICY4_DEPLOYER.deploy(
            admin, price_oracle.address, mock_factory.address, pk_array,
            634195839, 2 * 10**16, 10**17, 0, 86400,
        )

    new_pk = MOCK_PEG_KEEPER_DEPLOYER.deploy(10**18, boa.env.generate_address("stablecoin"))

    with boa.env.prank(admin):
        mp.add_peg_keeper(new_pk.address)
    
    # Verify AddPegKeeper event is emitted with new peg keeper address (must be right after call)
    logs = filter_logs(mp, "AddPegKeeper")
    assert len(logs) == 1
    assert logs[0].peg_keeper == new_pk.address

    assert mp.peg_keepers(0) == new_pk.address


def test_default_behavior_appends_to_array(mp, admin, peg_keepers):
    """New peg keeper is appended after existing ones."""
    new_pk = MOCK_PEG_KEEPER_DEPLOYER.deploy(10**18, boa.env.generate_address("stablecoin"))

    with boa.env.prank(admin):
        mp.add_peg_keeper(new_pk.address)

    # Original peg keepers unchanged
    for i, pk in enumerate(peg_keepers):
        assert mp.peg_keepers(i) == pk.address
    # New one appended
    assert mp.peg_keepers(len(peg_keepers)) == new_pk.address


def test_revert_unauthorized(mp):
    """Non-admin cannot add peg keeper."""
    unauthorized = boa.env.generate_address("unauthorized")
    new_pk = MOCK_PEG_KEEPER_DEPLOYER.deploy(10**18, boa.env.generate_address("stablecoin"))

    with boa.env.prank(unauthorized):
        with boa.reverts(dev="only admin"):
            mp.add_peg_keeper(new_pk.address)


def test_revert_zero_address(mp, admin):
    """Cannot add zero address as peg keeper."""
    with boa.env.prank(admin):
        with boa.reverts(dev="peg keeper is zero address"):
            mp.add_peg_keeper(ZERO_ADDRESS)


def test_revert_duplicate(mp, admin, peg_keepers):
    """Cannot add same peg keeper twice."""
    with boa.env.prank(admin):
        with boa.reverts("Already added"):
            mp.add_peg_keeper(peg_keepers[0].address)
