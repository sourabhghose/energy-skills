"""Arps model maths: rates, cumulatives, switch to terminal decline, decline conversions."""

import numpy as np
import pytest

from dca_models import (
    hyperbolic_cum,
    hyperbolic_rate,
    modified_cum,
    modified_rate,
    nominal_to_secant,
    nominal_to_tangent,
    secant_to_nominal,
    switch_time,
    tangent_to_nominal,
    terminal_effective_to_nominal,
    time_to_rate,
)


@pytest.mark.parametrize("b", [0.0, 0.5, 1.0, 1.5])
def test_cum_matches_numeric_integral(b):
    t = np.linspace(0, 20, 200001)
    q = hyperbolic_rate(t, 1000, 1.2, b)
    assert hyperbolic_cum(20, 1000, 1.2, b) == pytest.approx(np.trapezoid(q, t), rel=1e-6)


def test_modified_switches_at_terminal_decline():
    d_lim = terminal_effective_to_nominal(0.08)
    t_sw = switch_time(3.0, 1.3, d_lim)
    assert 3.0 / (1 + 1.3 * 3.0 * t_sw) == pytest.approx(d_lim)
    before, after = modified_rate([t_sw - 1e-9, t_sw + 1e-9], 800, 3.0, 1.3, d_lim)
    assert before == pytest.approx(after, rel=1e-6)          # continuous at the switch
    q1, q2 = modified_rate([t_sw + 1, t_sw + 2], 800, 3.0, 1.3, d_lim)
    assert 1 - q2 / q1 == pytest.approx(0.08, rel=1e-9)        # 8 %/yr effective after switch


def test_modified_cum_matches_integral():
    d_lim = terminal_effective_to_nominal(0.06)
    t = np.linspace(0, 40, 400001)
    assert modified_cum(40, 800, 3.0, 1.5, d_lim) == pytest.approx(
        np.trapezoid(modified_rate(t, 800, 3.0, 1.5, d_lim), t), rel=1e-6)


def test_terminal_decline_lowers_eur_for_high_b():
    d_lim = terminal_effective_to_nominal(0.08)
    assert modified_cum(50, 800, 3.0, 1.5, d_lim) < hyperbolic_cum(50, 800, 3.0, 1.5)


@pytest.mark.parametrize("b", [0.0, 0.8, 1.0, 1.4])
def test_time_to_rate_inverts(b):
    d_lim = terminal_effective_to_nominal(0.08)
    t = time_to_rate(4.0, 800, 2.5, b, d_lim)
    assert float(modified_rate(t, 800, 2.5, b, d_lim)) == pytest.approx(4.0, rel=1e-9)


def test_secant_vs_tangent_are_different():
    # 70 %/yr secant effective with b = 1.5 is a much larger nominal decline than 70 % tangent.
    d_sec = secant_to_nominal(0.70, 1.5)
    d_tan = tangent_to_nominal(0.70)
    assert d_sec == pytest.approx(((0.3) ** -1.5 - 1) / 1.5)
    assert d_sec > d_tan
    assert nominal_to_secant(d_sec, 1.5) == pytest.approx(0.70)
    assert nominal_to_tangent(d_tan) == pytest.approx(0.70)


def test_secant_equals_tangent_for_exponential():
    assert secant_to_nominal(0.3, 0.0) == pytest.approx(tangent_to_nominal(0.3))


def test_effective_decline_bounds():
    with pytest.raises(ValueError):
        secant_to_nominal(1.2, 1.0)
