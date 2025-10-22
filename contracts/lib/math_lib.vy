# TODO use this util everywhere: ctrl+f unsafe_sub(max(
@pure
@internal
def sub_or_zero(a: uint256, b: uint256) -> uint256:
    """Subtraction that floors at zero."""
    return unsafe_sub(max(a, b), b)
