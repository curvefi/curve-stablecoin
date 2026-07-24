"""Tests for HyperbolicDynamicMP.__init__ (constructor)."""

import boa
import pytest

from tests.utils import filter_logs
from tests.utils import hyperbolic_mp_reference as ref


def test_immutables_set(mp, controller, rate_calculator):
    assert mp.CONTROLLER() == controller.address
    assert mp.RATE_CALCULATOR() == rate_calculator.address


def test_parameters_match_reference(mp, default_params):
    u_inf, A, r_minf = ref.get_params(*default_params)

    p = mp.parameters()
    # (computed curve params) + (raw inputs echoed back), rate_shift = 0.
    assert (
        p.u_inf,
        p.A,
        p.r_minf,
        p.target_utilization,
        p.low_ratio,
        p.high_ratio,
        p.rate_shift,
    ) == (u_inf, A, r_minf) + default_params + (0,)


def test_target_rate_reads_calculator(mp):
    # target_rate reads the calculator's rate directly (in-bounds -> passthrough).
    assert mp.target_rate() == ref.DEFAULT_RATE


def test_ctor_emits_set_parameters(
    deployer, controller, rate_calculator, default_params
):
    mp = deployer.deploy(
        controller.address, rate_calculator.address, *default_params, 0
    )

    logs = filter_logs(mp, "SetParameters")
    assert len(logs) == 1
    e = logs[0]

    u_inf, A, r_minf = ref.get_params(*default_params)
    assert (
        e.u_inf,
        e.A,
        e.r_minf,
        e.target_utilization,
        e.low_ratio,
        e.high_ratio,
        e.rate_shift,
    ) == (u_inf, A, r_minf) + default_params + (0,)


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
def test_ctor_bounds_revert(deployer, controller, rate_calculator, args, err):
    with boa.reverts(err):
        deployer.deploy(controller.address, rate_calculator.address, *args)
