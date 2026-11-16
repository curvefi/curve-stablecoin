"""Pinned Ethereum wrapper/fee-module integration; all writes stay on the local fork."""

import os

import boa
import boa_solidity
import pytest
import solcx


BLOCK = 26350682  # Ethereum, 2026-11-05
WSTGBP = "0x57C3571f10767E49C9d7b60feb6c67804783B7aE"
ADMIN = "0xa73c94969dE90Edb159D29922C42fF24beDFA085"
ORACLE_SRC = "curve_stablecoin/price_oracles/v2/WstGBPFxOracle.sol"


def test_deployed_wrapper_fee_changes_and_capped_nav():
    rpc = os.getenv("ETHEREUM_RPC_URL") or os.getenv("MAINNET_RPC_URL")
    if not rpc:
        pytest.skip("Set ETHEREUM_RPC_URL or MAINNET_RPC_URL for the pinned fork test")

    with boa.fork(rpc, block_identifier=BLOCK, allow_dirty=True):
        wrapper = boa.loads_vyi("""
@external
@view
def navprice() -> uint256: ...
@external
@view
def burncost() -> uint256: ...
@external
@view
def act() -> address: ...
@external
@view
def pip() -> address: ...
""").at(WSTGBP)
        fees = boa.loads_vyi("""
@external
@view
def burncost(nav: uint256) -> uint256: ...
@external
def setBpsout(fee: uint256): ...
""").at(wrapper.act())
        pip = boa.loads_vyi("""
@external
def file(what: bytes32, data: bytes32): ...
""").at(wrapper.pip())
        # Fix GBP/USD at 1 to isolate the real wrapper's NAV and fee behavior.
        fx = boa.loads("""
@external
@pure
def price() -> uint256:
    return 10**18
@external
@pure
def price_w() -> uint256:
    return 10**18
""")
        solcx.set_solc_version("0.8.25")
        oracle = boa.load_partial_solc(ORACLE_SRC).deploy(WSTGBP, fx.address)
        nav = wrapper.navprice()
        assert oracle.price() == wrapper.burncost() == fees.burncost(nav)

        for fee in (5000, 9999, 10000, 0):
            fees.setBpsout(fee, sender=ADMIN)
            assert oracle.price() == oracle.price_w() == max(1, wrapper.burncost())
            assert oracle.cachedRedemptionRate() == wrapper.burncost()
            assert oracle.navAnchor() == nav

        # Apply the real fee module to a capped quote rather than the inflated NAV.
        pip.file(b"price".ljust(32, b"\0"), (2 * nav).to_bytes(32, "big"), sender=ADMIN)
        fees.setBpsout(25, sender=ADMIN)
        boa.env.time_travel(seconds=61)
        capped_nav = nav * (10**18 + oracle.MAX_UPSIDE_SPEED() * 61) // 10**18
        expected = fees.burncost(capped_nav)
        assert oracle.price() == oracle.price_w() == expected
        assert oracle.navAnchor() == capped_nav
        assert expected < wrapper.burncost()
