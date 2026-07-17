"""Tests for HyperbolicMP.set_parameters (admin-gated reconfiguration)."""

import boa
import pytest

from tests.utils import filter_logs
from tests.utils import hyperbolic_mp_reference as ref


# (target_utilization, target_rate, low_ratio, high_ratio, rate_shift)
_NEW = (5 * 10**17, 2 * ref.DEFAULT_RATE, 8 * 10**17, 5 * 10**18, 10**9)


def test_set_parameters_updates_curve(mp, admin):
    with boa.env.prank(admin):
        mp.set_parameters(*_NEW)

    u0, r0, alpha, beta, shift = _NEW
    u_inf, A, r_minf = ref.get_params(u0, alpha, beta)
    p = mp.parameters()
    assert (
        p.u_inf,
        p.A,
        p.r_minf,
        p.target_utilization,
        p.target_rate,
        p.low_ratio,
        p.high_ratio,
        p.rate_shift,
    ) == (u_inf, A, r_minf, u0, r0, alpha, beta, shift)


def test_set_parameters_emits_event(mp, admin):
    with boa.env.prank(admin):
        mp.set_parameters(*_NEW)

    logs = filter_logs(mp, "SetParameters")
    assert len(logs) == 1
    e = logs[0]

    u0, r0, alpha, beta, shift = _NEW
    u_inf, A, r_minf = ref.get_params(u0, alpha, beta)
    assert (
        e.u_inf,
        e.A,
        e.r_minf,
        e.target_utilization,
        e.target_rate,
        e.low_ratio,
        e.high_ratio,
        e.rate_shift,
    ) == (u_inf, A, r_minf, u0, r0, alpha, beta, shift)


def test_set_parameters_only_factory_admin(mp):
    stranger = boa.env.generate_address("stranger")
    with boa.env.prank(stranger):
        with boa.reverts("Not factory admin"):
            mp.set_parameters(*_NEW)


def test_set_parameters_follows_admin_change(mp, factory):
    # Access control reads the factory admin live, so rotating it works.
    new_admin = boa.env.generate_address("new_admin")
    factory.set_admin(new_admin)
    with boa.env.prank(new_admin):
        mp.set_parameters(*_NEW)


# Valid target_rate used for the non-target_rate bounds cases.
_R = ref.DEFAULT_RATE


@pytest.mark.parametrize(
    ("args", "err"),
    [
        (
            (ref.MIN_TARGET_UTIL - 1, _R, 5 * 10**17, 2 * 10**18, 0),
            "target_utilization too low",
        ),
        (
            (ref.MAX_TARGET_UTIL + 1, _R, 5 * 10**17, 2 * 10**18, 0),
            "target_utilization too high",
        ),
        (
            (85 * 10**16, ref.MIN_TARGET_RATE - 1, 5 * 10**17, 2 * 10**18, 0),
            "target_rate too low",
        ),
        (
            (85 * 10**16, ref.MAX_TARGET_RATE + 1, 5 * 10**17, 2 * 10**18, 0),
            "target_rate too high",
        ),
        (
            (85 * 10**16, _R, ref.MIN_LOW_RATIO - 1, 2 * 10**18, 0),
            "low_ratio too low",
        ),
        ((85 * 10**16, _R, 10**18, 2 * 10**18, 0), "low_ratio too high"),
        ((85 * 10**16, _R, 5 * 10**17, 10**18, 0), "high_ratio too low"),
        (
            (85 * 10**16, _R, 5 * 10**17, ref.MAX_HIGH_RATIO + 1, 0),
            "high_ratio too high",
        ),
        (
            (85 * 10**16, _R, 5 * 10**17, 2 * 10**18, ref.MAX_RATE_SHIFT + 1),
            "rate_shift too high",
        ),
        # Per-field checks pass, but the curve math is invalid (numerator <
        # subtrahend + WAD): low target_utilization with moderate ratios.
        ((ref.MIN_TARGET_UTIL, _R, 5 * 10**17, 2 * 10**18, 0), "invalid curve"),
        # Passes inner >= WAD but u_inf floors to exactly WAD (alpha near WAD ->
        # tiny subtrahend, large beta -> large numerator).
        ((5 * 10**17, _R, 10**18 - 1, 3 * 10**18, 0), "u_inf <= 100%"),
    ],
)
def test_set_parameters_bounds_revert(mp, admin, args, err):
    with boa.env.prank(admin):
        with boa.reverts(err):
            mp.set_parameters(*args)
