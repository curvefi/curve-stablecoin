from curve_stablecoin.interfaces import IController
from curve_stablecoin.interfaces import IAMM


@internal
@view
def users_with_health(
    controller: IController,
    _from: uint256,
    _limit: uint256,
    threshold: int256,
    require_approval: bool,
    approval_spender: address,
    full: bool,
) -> DynArray[IController.Position, 1000]:
    """
    Enumerate controller loans and return positions with health < threshold.
    Optionally require controller.approval(user, approval_spender).
    Returns IController.Position entries (user, x, y, debt, health).
    """
    AMM: IAMM = staticcall controller.amm()

    n_loans: uint256 = staticcall controller.n_loans()
    limit: uint256 = _limit if _limit != 0 else n_loans
    ix: uint256 = _from
    out: DynArray[IController.Position, 1000] = []
    for i: uint256 in range(10**6):
        if ix >= n_loans or i == limit:
            break
        user: address = staticcall controller.loans(ix)
        h: int256 = staticcall controller.health(user, full)
        ok: bool = h < threshold
        if ok and require_approval:
            ok = staticcall controller.approval(user, approval_spender)
        if ok:
            xy: uint256[2] = staticcall AMM.get_sum_xy(user)
            debt: uint256 = staticcall controller.debt(user)
            out.append(
                IController.Position(
                    user=user, x=xy[0], y=xy[1], debt=debt, health=h
                )
            )
        ix += 1
    return out
