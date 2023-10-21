# @version 0.3.9


interface Controller:
    def total_debt() -> uint256: view
    def set_debt(debt: uint256): nonpayable


n_collaterals: public(uint256)
controllers: public(HashMap[uint256, address])
debt_ceiling: public(HashMap[address, uint256])


@external
def add_market(controller: address, ceiling: uint256):
    n: uint256 = self.n_collaterals
    self.n_collaterals = n + 1
    self.controllers[n] = controller
    self.debt_ceiling[controller] = ceiling


@external
def set_debt(controller: address, debt: uint256):
    Controller(controller).set_debt(debt)


@external
def total_debt() -> uint256:
    total: uint256 = 0
    for i in range(10000):
        if i == self.n_collaterals:
            break
        total += Controller(self.controllers[i]).total_debt()
    return total

