# pragma version 0.4.3
from contracts.interfaces import IPriceOracle
from contracts import constants as c


COIN0_ORACLE: public(immutable(IPriceOracle))


@deploy
def __init__(coin0_oracle: IPriceOracle):
    COIN0_ORACLE = coin0_oracle


@internal
@view
def _coin0_oracle_price() -> uint256:
    if COIN0_ORACLE.address != empty(address):
        return staticcall COIN0_ORACLE.price()
    else:
        return c.WAD


@internal
def _coin0_oracle_price_w() -> uint256:
    if COIN0_ORACLE.address != empty(address):
        return extcall COIN0_ORACLE.price_w()
    else:
        return c.WAD
