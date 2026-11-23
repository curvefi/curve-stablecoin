# pragma version 0.4.3

"""
This contract is for testing only.
If you see it on mainnet - it won't be used for anything except testing the actual deployment

A DummyRouter that also accepts an opaque route blob, the way a real aggregator does.
Such a blob is what makes aggregator calldata large, and carrying one that no longer
has to fit in the controller's CALLDATA_MAX_SIZE is the reason TransientLeverageZap
exists - so tests need an exchange whose calldata can be grown on demand.

`exchange_with_route` covers the realistic case: the route is a genuine ABI argument.
The `__default__` swap covers the boundary case: the exact byte sizes around the zap's
EXCHANGE_CALLDATA_MAX_SIZE are not reachable through a typed argument (ABI encoding
lands on 32-byte steps and Vyper rejects trailing bytes), so the fallback performs a
swap set up in advance and reports how many bytes of calldata the zap forwarded to it.
"""

from curve_std.interfaces import IERC20

ROUTE_MAX_SIZE: constant(uint256) = 32 * 1100

last_route_size: public(uint256)
last_calldata_size: public(uint256)

# Swap the fallback performs, whatever it is called with
next_in_coin: public(address)
next_out_coin: public(address)
next_in_amount: public(uint256)
next_out_amount: public(uint256)


@internal
def _swap(in_coin: address, out_coin: address, in_amount: uint256, out_amount: uint256):
    assert extcall IERC20(in_coin).transferFrom(msg.sender, self, in_amount, default_return_value=True)
    assert extcall IERC20(out_coin).transfer(msg.sender, out_amount, default_return_value=True)


@external
def set_next_swap(in_coin: address, out_coin: address, in_amount: uint256, out_amount: uint256):
    self.next_in_coin = in_coin
    self.next_out_coin = out_coin
    self.next_in_amount = in_amount
    self.next_out_amount = out_amount


@external
def exchange_with_route(
    in_coin: address,
    out_coin: address,
    in_amount: uint256,
    out_amount: uint256,
    route: Bytes[ROUTE_MAX_SIZE],
):
    self.last_route_size = len(route)
    self.last_calldata_size = len(msg.data)
    self._swap(in_coin, out_coin, in_amount, out_amount)


@external
def __default__():
    self.last_calldata_size = len(msg.data)
    self._swap(
        self.next_in_coin,
        self.next_out_coin,
        self.next_in_amount,
        self.next_out_amount,
    )
