from vyper.interfaces import ERC20

STABLECOIN: immutable(ERC20)
COLLATERAL: immutable(ERC20)

price: public(uint256)


@external
def __init__(stablecoin_token: ERC20, collateral_token: ERC20, controller: address, price: uint256):
    STABLECOIN = stablecoin_token
    COLLATERAL = collateral_token
    self.price = price

    # It is necessary to approve transfers of these tokens by the controller
    stablecoin_token.approve(controller, max_value(uint256))
    collateral_token.approve(controller, max_value(uint256))

    # This contract will just receive funding in tokens and "swap" them according to the price


@external
def leverage(user: address, stablecoins_no_use: uint256, collateral: uint256, debt: uint256, extra_args: DynArray[uint256, 5]) -> uint256[2]:
    min_amount: uint256 = extra_args[0]
    assert STABLECOIN.balanceOf(self) >= debt
    amount_out: uint256 = debt * 10**18 / self.price
    assert amount_out >= min_amount
    return [0, amount_out]


@external
def deleverage(user: address, stablecoins: uint256, collateral: uint256, debt: uint256, extra_args: DynArray[uint256, 5]) -> uint256[2]:
    min_amount: uint256 = extra_args[0]
    s_diff: uint256 = debt - stablecoins
    assert s_diff >= min_amount
    # Instead of returning collateral - what_was_spent we could unwrap and send
    # ETH from here to user (if it was ETH), so no need to do it in controller
    return [s_diff, collateral - s_diff * 10**18 / self.price]
