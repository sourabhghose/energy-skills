"""Bounded Arps / modified-hyperbolic fitting on log rate (numpy only, deterministic).

For fixed (b, di) the best log(qi) in log space is closed-form (mean residual), so the fit
searches only (b, log di) on a bounded grid and then zooms in around the best cell. The
search can never leave the user's b-bounds, needs no initial guess, and returns the same
answer on every run.

Usage:
    from dca_fit import fit_decline
    fit = fit_decline(t_years, rate_per_day, b_bounds=(0.0, 1.5), d_lim=0.0834)
    fit.qi, fit.di, fit.b, fit.r2_log
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dca_models import B_EPS, switch_time

LOG_DI_RANGE = (np.log(1e-3), np.log(200.0))   # nominal 1/yr
COARSE_B, COARSE_D, ZOOM_STEPS, ZOOM_POINTS = 41, 121, 4, 21


@dataclass(frozen=True)
class DeclineFit:
    qi: float
    di: float
    b: float
    d_lim: float | None
    sse_log: float
    r2_log: float
    n_points: int
    b_bounds: tuple[float, float]


def _log_shape(t: np.ndarray, d: np.ndarray, b: float, d_lim: float | None) -> np.ndarray:
    """log(q/qi) for every di in d (rows) at every t (columns)."""
    dt = d[:, None] * t[None, :]
    if b < B_EPS:
        hyp = -dt
    else:
        hyp = -np.log1p(b * dt) / b
    if d_lim is None:
        return hyp
    t_sw = np.array([switch_time(float(di), b, d_lim) for di in d])
    finite = np.isfinite(t_sw)
    t_sw_safe = np.where(finite, t_sw, 0.0)
    if b < B_EPS:
        at_sw = -d * t_sw_safe
    else:
        at_sw = -np.log1p(b * d * t_sw_safe) / b
    tail = at_sw[:, None] - d_lim * (t[None, :] - t_sw_safe[:, None])
    use_tail = finite[:, None] & (t[None, :] > t_sw_safe[:, None])
    return np.where(use_tail, tail, hyp)


def _best_for_b(t, logq, logd, b, d_lim):
    shape = _log_shape(t, np.exp(logd), b, d_lim)
    log_qi = np.mean(logq[None, :] - shape, axis=1)
    sse = np.sum((logq[None, :] - log_qi[:, None] - shape) ** 2, axis=1)
    i = int(np.argmin(sse))
    return float(sse[i]), float(logd[i]), float(log_qi[i])


def _search(t, logq, b_grid, logd_grid, d_lim):
    best = (np.inf, None, None, None)
    for b in b_grid:
        sse, logd, log_qi = _best_for_b(t, logq, logd_grid, float(b), d_lim)
        if sse < best[0]:
            best = (sse, float(b), logd, log_qi)
    return best


def _zoom_grid(center: float, step: float, lo: float, hi: float) -> np.ndarray:
    return np.unique(np.clip(np.linspace(center - step, center + step, ZOOM_POINTS), lo, hi))


def fit_decline(t, rate, b_bounds: tuple[float, float], d_lim: float | None) -> DeclineFit:
    """Fit qi, di, b to rate-time data on log rate, with b constrained to b_bounds."""
    t = np.asarray(t, dtype=float)
    q = np.asarray(rate, dtype=float)
    if t.shape != q.shape or t.size < 3:
        raise ValueError("need at least 3 matching (t, rate) points to fit a decline")
    if np.any(q <= 0) or np.any(~np.isfinite(q)) or np.any(~np.isfinite(t)):
        raise ValueError("rates must be positive and finite; filter shut-in periods first")
    b_lo, b_hi = float(b_bounds[0]), float(b_bounds[1])
    if not 0.0 <= b_lo <= b_hi:
        raise ValueError(f"invalid b_bounds {b_bounds}")
    logq = np.log(q)
    b_grid = np.linspace(b_lo, b_hi, 1 if b_hi == b_lo else COARSE_B)
    logd_grid = np.linspace(*LOG_DI_RANGE, COARSE_D)
    sse, b, logd, log_qi = _search(t, logq, b_grid, logd_grid, d_lim)
    b_step = (b_hi - b_lo) / max(COARSE_B - 1, 1)
    d_step = (LOG_DI_RANGE[1] - LOG_DI_RANGE[0]) / (COARSE_D - 1)
    for _ in range(ZOOM_STEPS):
        b_grid = np.array([b]) if b_hi == b_lo else _zoom_grid(b, b_step, b_lo, b_hi)
        sse, b, logd, log_qi = _search(t, logq, b_grid, _zoom_grid(logd, d_step, *LOG_DI_RANGE), d_lim)
        b_step, d_step = b_step / 5.0, d_step / 5.0
    sst = float(np.sum((logq - logq.mean()) ** 2))
    r2 = 1.0 - sse / sst if sst > 0 else 1.0
    return DeclineFit(qi=float(np.exp(log_qi)), di=float(np.exp(logd)), b=b, d_lim=d_lim,
                      sse_log=float(sse), r2_log=float(r2), n_points=int(t.size), b_bounds=(b_lo, b_hi))
