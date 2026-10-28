"""Type curves and EUR distributions with the PRMS percentile convention.

PRMS convention: P90 is the LOW estimate (90% probability the outcome is at least this),
P10 is the HIGH estimate. So P10 = 90th percentile of the distribution and P90 = 10th
percentile. Labelling np.percentile(x, 10) as "P10" is the classic mistake; this module
names columns by the PRMS meaning and asserts P10 >= P50 >= P90.

Usage:
    from dca_typecurve import build_type_curve, eur_percentiles
    tc = build_type_curve(wells, decisions, tc_decisions, min_wells=5)
    tc.curve        # month_index, n_wells, p10/p50/p90/mean normalized rate per day
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from dca_config import DcaDecisions, TypeCurveDecisions
from dca_fit import DeclineFit, fit_decline
from dca_models import terminal_effective_to_nominal
from dca_prep import condition_well


@dataclass(frozen=True)
class TypeCurve:
    curve: pd.DataFrame
    fits: dict[str, DeclineFit | None]
    wells_used: list[str]
    wells_excluded: dict[str, str]


def prms_percentiles(values) -> dict[str, float]:
    """P10 (high) / P50 / P90 (low) under the PRMS exceedance convention."""
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return {"p10_high": np.nan, "p50": np.nan, "p90_low": np.nan, "mean": np.nan, "n": 0}
    out = {"p10_high": float(np.quantile(x, 0.9)), "p50": float(np.quantile(x, 0.5)),
           "p90_low": float(np.quantile(x, 0.1)), "mean": float(x.mean()), "n": int(x.size)}
    assert out["p10_high"] >= out["p50"] >= out["p90_low"]
    return out


def _scale(lateral_ft, tcd: TypeCurveDecisions) -> float | None:
    if tcd.normalization == "none":
        return 1.0
    if lateral_ft is None or not np.isfinite(lateral_ft) or lateral_ft <= 0:
        return None
    return tcd.reference_lateral_ft / float(lateral_ft)


def eur_percentiles(eur_by_well: dict[str, float], lateral_by_well: dict[str, float],
                    tcd: TypeCurveDecisions) -> dict[str, float]:
    """PRMS percentiles of (optionally lateral-normalized) per-well EURs."""
    scaled = [eur * s for w, eur in eur_by_well.items()
              if (s := _scale(lateral_by_well.get(w), tcd)) is not None]
    return prms_percentiles(scaled)


def _aligned_rates(wells: dict[str, pd.DataFrame], laterals: dict[str, float], decisions: DcaDecisions,
                   tcd: TypeCurveDecisions) -> tuple[pd.DataFrame, dict[str, str]]:
    rows, excluded = [], {}
    for well_id, pdf in wells.items():
        scale = _scale(laterals.get(well_id), tcd)
        if scale is None:
            excluded[well_id] = "missing_or_invalid_lateral_length"
            continue
        cw = condition_well(pdf, "monthly", decisions.rate_basis, decisions.decline_start, decisions.outlier_method)
        post = cw.frame[cw.frame["period_start"] >= cw.decline_start]
        month_index = np.arange(len(post))
        rate = post["rate"].where(post["include"]).to_numpy() * scale
        rows.append(pd.DataFrame({"well_id": well_id, "month_index": month_index, "rate": rate}))
    if not rows:
        return pd.DataFrame(columns=["well_id", "month_index", "rate"]), excluded
    return pd.concat(rows, ignore_index=True), excluded


def _percentile_curve(aligned: pd.DataFrame, min_wells: int) -> pd.DataFrame:
    records = []
    for month, grp in aligned.dropna(subset=["rate"]).groupby("month_index"):
        stats = prms_percentiles(grp["rate"].to_numpy())
        if stats["n"] >= min_wells:
            records.append({"month_index": int(month), "n_wells": stats["n"], "p10_high_rate": stats["p10_high"],
                            "p50_rate": stats["p50"], "p90_low_rate": stats["p90_low"], "mean_rate": stats["mean"]})
    return pd.DataFrame(records)


def _fit_series(curve: pd.DataFrame, column: str, decisions: DcaDecisions) -> DeclineFit | None:
    if len(curve) < 3:
        return None
    t = (curve["month_index"].to_numpy() + 0.5) / 12.0
    d_lim = (None if decisions.terminal_decline_eff is None
             else terminal_effective_to_nominal(decisions.terminal_decline_eff))
    return fit_decline(t, curve[column].to_numpy(), decisions.b_bounds, d_lim)


def build_type_curve(wells: dict[str, pd.DataFrame], laterals: dict[str, float], decisions: DcaDecisions,
                     tcd: TypeCurveDecisions, min_wells: int = 5) -> TypeCurve:
    """Peak-aligned monthly percentile type curve, truncated where fewer than min_wells remain.

    Truncation guards against survivor bias: late months are populated only by the oldest
    (often best) wells, which drags the tail of an average curve upward.
    """
    aligned, excluded = _aligned_rates(wells, laterals, decisions, tcd)
    curve = _percentile_curve(aligned, min_wells)
    fits = {col: _fit_series(curve, col, decisions) for col in ("p10_high_rate", "p50_rate", "p90_low_rate")} \
        if not curve.empty else {}
    used = sorted(set(aligned["well_id"])) if not aligned.empty else []
    return TypeCurve(curve=curve, fits=fits, wells_used=used, wells_excluded=excluded)
