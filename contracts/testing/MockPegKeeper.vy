# @version 0.3.9

debt: public(uint256)


@external
def set_debt(d: uint256):
    self.debt = d
