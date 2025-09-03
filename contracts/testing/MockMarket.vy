# pragma version 0.4.3


total_debt: public(uint256)


@external
def set_debt(d: uint256):
    self.total_debt = d
