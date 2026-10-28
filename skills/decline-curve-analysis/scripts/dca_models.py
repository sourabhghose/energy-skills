"""Arps decline models and decline-rate conversions (pure numpy).

Conventions used throughout this skill:
  * t is time in YEARS from the start of decline (t = 0 at the decline-start period start).
  * q is a RATE per DAY (e.g. bbl/d, Mcf/d).
  * di, d_lim are NOMINAL (instantaneous) declines in 1/year.
  * Cumulative functions return rate x years; multiply by DAYS_PER_YEAR for volume.

Models:
  hyperbolic  q = qi / (1 + b di t)^(1/b)            (b -> 0 exponential, b = 1 harmonic)
  modified    hyperbolic until the instantaneous nominal decline di / (1 + b di t) falls
              to d_lim, then exponential at d_lim (terminal decline).

Decline-rate forms (annual): nominal D, tangent effective De_t = 1 - exp(-D), and secant
effective De_s = 1 - (1 + b D)^(-1/b) (the SPEE convention for hyperbolic declines).

Usage:
    from dca_models import modified_rate, modified_cum, secant_to_nominal
    di = secant_to_nominal(0.65, b=1.2)          # 65 %/yr secant effective -> nominal
"""

from __future__ import annotations

import numpy as np

DAYS_PER_YEAR = 365.25
B_EPS = 1e-6


def hyperbolic_rate(t, qi: float, di: float, b: float):
    """Arps rate at time t (years)."""
    t = np.asarray(t, dtype=float)
    if b < B_EPS:
        return qi * np.exp(-di * t)
    return qi / np.power(1.0 + b * di * t, 1.0 / b)


def hyperbolic_cum(t, qi: float, di: float, b: float):
    """Arps cumulative from 0 to t, in rate x years."""
    t = np.asarray(t, dtype=float)
    if b < B_EPS:
        return qi / di * (1.0 - np.exp(-di * t))
    if abs(b - 1.0) < B_EPS:
        return qi / di * np.log1p(di * t)
    return qi / ((1.0 - b) * di) * (1.0 - np.power(1.0 + b * di * t, (b - 1.0) / b))


def instantaneous_decline(t, di: float, b: float):
    """Nominal decline D(t) = di / (1 + b di t), 1/year."""
    return di / (1.0 + b * di * np.asarray(t, dtype=float))


def switch_time(di: float, b: float, d_lim: float | None) -> float:
    """Time (years) at which hyperbolic decline reaches d_lim; inf if never."""
    if d_lim is None or d_lim <= 0:
        return float("inf")
    if di <= d_lim:
        return 0.0
    if b < B_EPS:
        return float("inf")
    return (di / d_lim - 1.0) / (b * di)


def modified_rate(t, qi: float, di: float, b: float, d_lim: float | None):
    """Modified-hyperbolic rate: hyperbolic, then exponential at d_lim."""
    t = np.asarray(t, dtype=float)
    t_sw = switch_time(di, b, d_lim)
    if not np.isfinite(t_sw):
        return hyperbolic_rate(t, qi, di, b)
    q_sw = float(hyperbolic_rate(t_sw, qi, di, b))
    tail = q_sw * np.exp(-d_lim * np.clip(t - t_sw, 0.0, None))
    return np.where(t <= t_sw, hyperbolic_rate(np.minimum(t, t_sw), qi, di, b), tail)


def modified_cum(t, qi: float, di: float, b: float, d_lim: float | None):
    """Modified-hyperbolic cumulative from 0 to t, in rate x years."""
    t = np.asarray(t, dtype=float)
    t_sw = switch_time(di, b, d_lim)
    if not np.isfinite(t_sw):
        return hyperbolic_cum(t, qi, di, b)
    q_sw = float(hyperbolic_rate(t_sw, qi, di, b))
    head = hyperbolic_cum(np.minimum(t, t_sw), qi, di, b)
    tail = q_sw / d_lim * (1.0 - np.exp(-d_lim * np.clip(t - t_sw, 0.0, None)))
    return head + np.where(t > t_sw, tail, 0.0)


def time_to_rate(q: float, qi: float, di: float, b: float, d_lim: float | None) -> float:
    """Time (years) when the modified-hyperbolic rate falls to q; 0 if qi <= q."""
    if q >= qi:
        return 0.0
    t_sw = switch_time(di, b, d_lim)
    q_sw = float(hyperbolic_rate(t_sw, qi, di, b)) if np.isfinite(t_sw) else 0.0
    if q >= q_sw:
        if b < B_EPS:
            return float(np.log(qi / q) / di)
        return float(((qi / q) ** b - 1.0) / (b * di))
    return float(t_sw + np.log(q_sw / q) / d_lim)


# --- Decline-rate conversions (annual) ----------------------------------------------


def nominal_to_secant(d: float, b: float) -> float:
    """Nominal -> secant effective annual decline (SPEE convention)."""
    if b < B_EPS:
        return float(1.0 - np.exp(-d))
    return float(1.0 - (1.0 + b * d) ** (-1.0 / b))


def secant_to_nominal(de: float, b: float) -> float:
    """Secant effective annual decline -> nominal (1/yr)."""
    _check_fraction(de)
    if b < B_EPS:
        return float(-np.log(1.0 - de))
    return float(((1.0 - de) ** (-b) - 1.0) / b)


def nominal_to_tangent(d: float) -> float:
    """Nominal -> tangent effective annual decline: 1 - exp(-D)."""
    return float(1.0 - np.exp(-d))


def tangent_to_nominal(de: float) -> float:
    """Tangent effective annual decline -> nominal (1/yr)."""
    _check_fraction(de)
    return float(-np.log(1.0 - de))


def terminal_effective_to_nominal(de: float) -> float:
    """Terminal (exponential) effective annual decline -> nominal; tangent == secant at b = 0."""
    return tangent_to_nominal(de)


def _check_fraction(de: float) -> None:
    if not 0.0 < de < 1.0:
        raise ValueError(f"effective decline must be a fraction in (0, 1), got {de}")
