"""Tests for HyperbolicDynamicMP.set_parameters (admin-gated reconfiguration)."""

import boa
import pytest

from tests.utils import filter_logs
from tests.utils import hyperbolic_mp_reference as ref


def test_set_parameters_updates_curve(mp, admin):
    new = (5 * 10**17, 8 * 10**17, 5 * 10**18, 10**9)
    with boa.env.prank(admin):
        mp.set_parameters(*new)

    u_inf, A, r_minf = ref.get_params(*new[:3])
    p = mp.parameters()
    assert (
        p.u_inf,
        p.A,
        p.r_minf,
        p.target_utilization,
        p.low_ratio,
        p.high_ratio,
        p.rate_shift,
    ) == (u_inf, A, r_minf) + new


def test_set_parameters_emits_event(mp, admin):
    new = (5 * 10**17, 8 * 10**17, 5 * 10**18, 10**9)
    with boa.env.prank(admin):
        mp.set_parameters(*new)

    logs = filter_logs(mp, "SetParameters")
    assert len(logs) == 1
    e = logs[0]

    u_inf, A, r_minf = ref.get_params(*new[:3])
    assert (
        e.u_inf,
        e.A,
        e.r_minf,
        e.target_utilization,
        e.low_ratio,
        e.high_ratio,
        e.rate_shift,
    ) == (u_inf, A, r_minf) + new


def test_set_parameters_only_factory_admin(mp):
    stranger = boa.env.generate_address("stranger")
    with boa.env.prank(stranger):
        with boa.reverts("Not factory admin"):
            mp.set_parameters(5 * 10**17, 8 * 10**17, 5 * 10**18, 0)


def test_set_parameters_follows_admin_change(mp, factory):
    # Access control reads the factory admin live, so rotating it works.
    new_admin = boa.env.generate_address("new_admin")
    factory.set_admin(new_admin)
    with boa.env.prank(new_admin):
        mp.set_parameters(5 * 10**17, 8 * 10**17, 5 * 10**18, 0)


@pytest.mark.parametrize(
    ("args", "err"),
    [
        (
            (ref.MIN_TARGET_UTIL - 1, 5 * 10**17, 2 * 10**18, 0),
            "target_utilization too low",
        ),
        (
            (ref.MAX_TARGET_UTIL + 1, 5 * 10**17, 2 * 10**18, 0),
            "target_utilization too high",
        ),
        ((85 * 10**16, ref.MIN_LOW_RATIO - 1, 2 * 10**18, 0), "low_ratio too low"),
        ((85 * 10**16, 10**18, 2 * 10**18, 0), "low_ratio too high"),
        ((85 * 10**16, 5 * 10**17, 10**18, 0), "high_ratio too low"),
        ((85 * 10**16, 5 * 10**17, ref.MAX_HIGH_RATIO + 1, 0), "high_ratio too high"),
        (
            (85 * 10**16, 5 * 10**17, 2 * 10**18, ref.MAX_RATE_SHIFT + 1),
            "rate_shift too high",
        ),
        # Per-field checks pass, but the curve math is invalid (numerator <
        # subtrahend + WAD): low target_utilization with moderate ratios.
        ((ref.MIN_TARGET_UTIL, 5 * 10**17, 2 * 10**18, 0), "invalid curve"),
        # Passes inner >= WAD but u_inf floors to exactly WAD (alpha near WAD ->
        # tiny subtrahend, large beta -> large numerator).
        ((5 * 10**17, 10**18 - 1, 3 * 10**18, 0), "u_inf <= 100%"),
    ],
)
def test_set_parameters_bounds_revert(mp, admin, args, err):
    with boa.env.prank(admin):
        with boa.reverts(err):
            mp.set_parameters(*args)
