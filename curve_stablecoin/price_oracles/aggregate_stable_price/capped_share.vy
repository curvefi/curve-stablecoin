# pragma version 0.4.3

MAX_N: constant(uint256) = 64
WAD: constant(uint256) = 10**18
MIN_SHARE: constant(uint256) = WAD // 100  # 1%

custom_share_cap: public(uint256)

event SetShareCap:
    share_cap: uint256


@internal
@pure
def _default_cap(n_active: uint256) -> uint256:
    """
    @dev Default cap schedule based on the number of active sources.
    @param n_active Number of active price sources.
    @return WAD-scaled default share cap.
    """
    if n_active <= 1:
        return WAD
    elif n_active == 2:
        return 70 * (WAD // 100)  # 0.7
    elif n_active <= 5:
        return 45 * (WAD // 100)  # 0.45
    else:
        return 24 * (WAD // 100)  # 0.24


@external
@pure
def default_cap(n_active: uint256) -> uint256:
    """
    @notice Return the default cap for a given active source count.
    @param n_active Number of active price sources.
    @return WAD-scaled default share cap.
    """
    return self._default_cap(n_active)


@internal
@view
def share_cap(n_active: uint256) -> uint256:
    """
    @dev Return the custom cap if set, otherwise the default cap.
    @param n_active Number of active price sources.
    @return WAD-scaled effective share cap.
    """
    max_share: uint256 = self.custom_share_cap
    if max_share == 0:
        max_share = self._default_cap(n_active)
    return max_share


@internal
def set_custom_share_cap(_share_cap: uint256):
    """
    @dev Persist a custom share cap and emit the module event.
    @param _share_cap WAD-scaled custom cap.
    """
    assert _share_cap == 0 or _share_cap >= MIN_SHARE, "share cap too low"
    assert _share_cap <= WAD, "share cap too high"
    self.custom_share_cap = _share_cap
    log SetShareCap(share_cap=_share_cap)


@internal
@view
def capped_weights(
    D: DynArray[uint256, MAX_N]
) -> DynArray[uint256, MAX_N]:
    """
    @notice Calculate TVL weights with an upper per-source relative share cap.
    @param D Active source TVLs.
    @return Relative WAD-scaled capped weights aligned to `D`; the sum is
            not guaranteed to equal WAD.
    """
    n_sources: uint256 = len(D)
    max_share: uint256 = self.share_cap(n_sources)

    Dsum: uint256 = 0
    # Water-filling with an upper cap:
    #   weight[i] = min(max_share, D[i] * remaining_share / remaining_Dsum)
    # Each pass fixes newly capped sources, then redistributes the remaining
    # share over the still-uncapped liquidity.
    weights: DynArray[uint256, MAX_N] = []
    for d: uint256 in D:
        Dsum += d
        weights.append(0)

    remaining_Dsum: uint256 = Dsum
    remaining_share: uint256 = WAD

    # At most floor((WAD - 1) / max_share) sources can be capped before
    # the remaining share is <= max_share. n_sources is also an upper bound:
    # each successful pass caps at least one active source.
    max_passes: uint256 = min(n_sources, unsafe_div(WAD - 1, max_share))
    for _: uint256 in range(max_passes, bound=MAX_N):
        did_cap: bool = False
        for i: uint256 in range(n_sources, bound=MAX_N):
            if weights[i] == 0:
                candidate_share: uint256 = unsafe_div(remaining_share * D[i], remaining_Dsum)
                if candidate_share > max_share:
                    weights[i] = max_share
                    remaining_Dsum -= D[i]
                    remaining_share -= max_share
                    did_cap = True
        if not did_cap:
            break

    for i: uint256 in range(n_sources, bound=MAX_N):
        if weights[i] == 0:
            weights[i] = unsafe_div(remaining_share * D[i], remaining_Dsum)

    return weights
