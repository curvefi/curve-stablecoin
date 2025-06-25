# pragma version 0.4.1

interface PriceOracle:
    def price() -> uint256: view
    def price_w() -> uint256: nonpayable

@deploy
def __init__(coin0_oracle: PriceOracle):
    COIN0_ORACLE = coin0_oracle

COIN0_ORACLE: public(immutable(PriceOracle))

@internal
@view
def _coin0_oracle_price() -> uint256:
    if COIN0_ORACLE.address != empty(address):
        return staticcall COIN0_ORACLE.price()
    else:
        return 10**18


@internal
def _coin0_oracle_price_w() -> uint256:
    if COIN0_ORACLE.address != empty(address):
        return extcall COIN0_ORACLE.price_w()
    else:
        return 10**18