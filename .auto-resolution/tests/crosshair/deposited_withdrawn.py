from z3 import Int, Solver

solver = Solver()


def Uint256(name: str):
    x = Int(name)
    solver.add(x >= 0, x < 2**256)
    return x


def assert_not_Uint256(x: Int):
    solver.add((x < 0) | (x >= 2**256))


# vault_deposited = Uint256("vault_deposited")
# vault_withdrawn = Uint256("vault_withdrawn")


# assert_not_Uint256(vault_deposited - vault_withdrawn)

# res = solver.check()

# if res == sat:
#     from pprint import pprint
#     pprint(solver.model())
