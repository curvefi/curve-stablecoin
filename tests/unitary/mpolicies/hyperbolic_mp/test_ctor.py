"""Tests for HyperbolicMP.__init__ (constructor)."""

import boa
import pytest

from tests.utils import filter_logs
from tests.utils import hyperbolic_mp_reference as ref


def test_immutables_set(mp, controller):
    assert mp.CONTROLLER() == controller.address


def test_parameters_match_reference(mp, default_curve, target_rate):
    u_inf, A, r_minf = ref.get_params(*default_curve)
    u0, alpha, beta = default_curve

    p = mp.parameters()
    # (computed curve params) + (raw inputs echoed back), rate_shift = 0.
    assert (
        p.u_inf,
        p.A,
        p.r_minf,
        p.target_utilization,
        p.target_rate,
        p.low_ratio,
        p.high_ratio,
        p.rate_shift,
    ) == (u_inf, A, r_minf, u0, target_rate, alpha, beta, 0)


def test_ctor_emits_set_parameters(deployer, controller, default_params, target_rate):
    mp = deployer.deploy(controller.address, *default_params, 0)

    logs = filter_logs(mp, "SetParameters")
    assert len(logs) == 1
    e = logs[0]

    u0, _, alpha, beta = default_params
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
    ) == (u_inf, A, r_minf, u0, target_rate, alpha, beta, 0)


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
def test_ctor_bounds_revert(deployer, controller, args, err):
    with boa.reverts(err):
        deployer.deploy(controller.address, *args)
