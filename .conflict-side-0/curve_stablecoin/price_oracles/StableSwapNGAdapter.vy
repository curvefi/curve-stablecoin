# pragma version 0.3.10
"""
@title StableSwapNGAdapter
@author Curve.Fi
@notice View contract to use -ng StableSwap in AggregateStablePrice with only old pools support
"""

interface Stableswap:
    def price_oracle(i: uint256) -> uint256: view


TARGET: public(immutable(Stableswap))


@external
def __init__(_address: Stableswap):
    TARGET = _address


@view
@external
def __default__() -> uint256:
    # Needed methods are view and return exactly 1 slot:
    #     def coins(i: uint256) -> address: view
    #     def get_virtual_price() -> uint256: view
    #     def totalSupply() -> uint256: view
    return convert(raw_call(TARGET.address, msg.data, max_outsize=32, is_static_call=True), uint256)


@view
@external
def price_oracle() -> uint256:
    return TARGET.price_oracle(0)
