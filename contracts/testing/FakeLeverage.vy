from vyper.interfaces import ERC20

STABLECOIN: immutable(ERC20)
COLLATERAL: immutable(ERC20)

price: public(uint256)


@external
def __init__(stablecoin_token: ERC20, collateral_token: ERC20, price: uint256, controller: address):
    STABLECOIN = stablecoin_token
    COLLATERAL = collateral_token
    self.price = price

    # It is necessary to approve transfers of these tokens by the controller
    stablecoin_token.approve(controller, max_value(uint256))
    collateral_token.approve(controller, max_value(uint256))

    # This contract will just receive funding in tokens and "swap" them according to the price


@external
def leverage(user: address, collateral: uint256, debt: uint256, extra_args: DynArray[uint256, 5]) -> uint256:
    min_amount: uint256 = extra_args[0]
    assert STABLECOIN.balanceOf(self) >= debt
    amount_out: uint256 = debt * 10**18 / self.price
    assert amount_out >= min_amount
    return amount_out


@external
def deleverage(user: address, stablecoins: uint256, collateral: uint256, debt: uint256, extra_args: DynArray[uint256, 5]) -> uint256[2]:
    min_amount: uint256 = extra_args[0]
    s_diff: uint256 = debt - stablecoins
    return [s_diff, collateral - s_diff * 10**18 / self.price]
