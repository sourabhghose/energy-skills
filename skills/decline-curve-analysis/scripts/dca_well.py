"""Per-well DCA: condition -> bounded fit -> EUR -> plausibility flags -> forecast.

Usage:
    from dca_config import DcaDecisions
    from dca_well import analyze_well, forecast_well
    result = analyze_well(pdf, period="monthly", decisions=decisions)
    result["eur"], result["flags"]
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from dca_config import DcaDecisions
from dca_fit import DeclineFit, fit_decline
from dca_models import (
    DAYS_PER_YEAR,
    modified_cum,
    modified_rate,
    nominal_to_secant,
    nominal_to_tangent,
    terminal_effective_to_nominal,
    time_to_rate,
)
from dca_prep import ConditionedWell, condition_well

logger = logging.getLogger(__name__)

MIN_POINTS, R2_MIN, B_HIGH, EUR_PEAK_YEARS_MAX = 6, 0.70, 2.0, 15.0


def _d_lim(decisions: DcaDecisions) -> float | None:
    if decisions.terminal_decline_eff is None:
        return None
    return terminal_effective_to_nominal(decisions.terminal_decline_eff)


def compute_eur(fit: DeclineFit, cw: ConditionedWell, decisions: DcaDecisions) -> dict:
    """EUR = cumulative to date + forecast from the last period to min(econ limit, max life)."""
    t_econ = time_to_rate(decisions.econ_limit_rate, fit.qi, fit.di, fit.b, fit.d_lim)
    t_life = decisions.max_life_years - cw.t_offset_years
    t_end = min(t_econ, t_life)
    remaining = 0.0
    if t_end > cw.t_last_years:
        q_cum = modified_cum(np.array([cw.t_last_years, t_end]), fit.qi, fit.di, fit.b, fit.d_lim)
        remaining = float(q_cum[1] - q_cum[0]) * DAYS_PER_YEAR
    return {
        "cum_to_date": cw.cum_volume,
        "t_last_years": cw.t_last_years,
        "remaining": remaining,
        "eur": cw.cum_volume + remaining,
        "t_end_years": float(t_end),
        "end_reason": "economic_limit" if t_econ <= t_life else "max_life",
        "rate_at_last": float(modified_rate(cw.t_last_years, fit.qi, fit.di, fit.b, fit.d_lim)),
    }


def plausibility_flags(fit: DeclineFit, eur: dict, peak_rate: float, decisions: DcaDecisions) -> list[str]:
    """Flags a reviewer should see before any EUR is booked."""
    flags = []
    lo, hi = fit.b_bounds
    if hi > lo and abs(fit.b - hi) < 1e-3:
        flags.append("b_at_upper_bound")
    if fit.b > B_HIGH:
        flags.append("b_above_2")
    if fit.b >= 1.0 and fit.d_lim is None:
        flags.append("hyperbolic_b_ge_1_without_terminal_decline")
    if fit.r2_log < R2_MIN:
        flags.append("poor_fit_r2_log")
    if fit.n_points < MIN_POINTS:
        flags.append("few_points")
    if peak_rate > 0 and eur["eur"] / (peak_rate * DAYS_PER_YEAR) > EUR_PEAK_YEARS_MAX:
        flags.append("eur_exceeds_15_years_at_peak_rate")
    if eur["rate_at_last"] <= decisions.econ_limit_rate:
        flags.append("already_below_economic_limit")
    if eur["end_reason"] == "max_life":
        flags.append("eur_truncated_by_max_life")
    return flags


def _fit_summary(fit: DeclineFit) -> dict:
    return {
        "qi_per_day": fit.qi, "di_nominal_per_yr": fit.di, "b": fit.b,
        "di_secant_eff": nominal_to_secant(fit.di, fit.b), "di_tangent_eff": nominal_to_tangent(fit.di),
        "d_lim_nominal_per_yr": fit.d_lim, "r2_log": fit.r2_log, "n_points": fit.n_points,
        "b_min": fit.b_bounds[0], "b_max": fit.b_bounds[1],
    }


def analyze_well(pdf: pd.DataFrame, period: str, decisions: DcaDecisions) -> dict:
    """Full analysis for one well; returns a flat dict (one output row)."""
    cw = condition_well(pdf, period, decisions.rate_basis, decisions.decline_start, decisions.outlier_method)
    pts = cw.frame[cw.frame["include"]]
    if len(pts) < 3:
        return {"status": "insufficient_data", "n_points": int(len(pts)), "exclusions": cw.exclusions,
                "cum_to_date": cw.cum_volume, "flags": ["few_points"]}
    fit = fit_decline(pts["t_years"].to_numpy(), pts["rate"].to_numpy(), decisions.b_bounds, _d_lim(decisions))
    eur = compute_eur(fit, cw, decisions)
    peak = float(cw.frame.loc[cw.frame["include"] | (cw.frame["exclude_reason"] == "pre_decline"), "rate"].max())
    return {
        "status": "ok", **_fit_summary(fit), **eur, "peak_rate_per_day": peak,
        "first_production": cw.first_production.date().isoformat(),
        "decline_start": cw.decline_start.date().isoformat(),
        "exclusions": cw.exclusions,
        "flags": plausibility_flags(fit, eur, peak, decisions),
    }


def forecast_well(result: dict) -> pd.DataFrame:
    """Monthly forecast volumes from the end of history to t_end, from an analyze_well row."""
    columns = ["month_index", "t_start_years", "volume", "rate_per_day"]
    if result.get("status") != "ok":
        return pd.DataFrame(columns=columns)
    t_last, t_end = result["t_last_years"], result["t_end_years"]
    n = int(np.ceil(max(t_end - t_last, 0.0) * 12))
    edges = np.minimum(t_last + np.arange(n + 1) / 12.0, max(t_end, t_last))
    args = (result["qi_per_day"], result["di_nominal_per_yr"], result["b"], result["d_lim_nominal_per_yr"])
    cum = modified_cum(edges, *args) * DAYS_PER_YEAR
    mid = (edges[:-1] + edges[1:]) / 2.0
    return pd.DataFrame({"month_index": np.arange(1, n + 1), "t_start_years": edges[:-1],
                         "volume": np.diff(cum), "rate_per_day": modified_rate(mid, *args)}, columns=columns)
