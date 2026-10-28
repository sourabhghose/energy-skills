"""Estimation (the E in VEE), register reconciliation, and anomaly indicators. Pure pandas.

Gap handling, in order:
1. gaps of ≤ ``linear_max_gap_intervals``: linear interpolation between valid neighbours;
2. longer gaps up to ``max_estimation_gap_hours`` with ``long_gap_method='like_day'``: mean of
   the same local time-of-day on the most recent valid like days (weekday vs weekend);
3. register-bracketed gaps: estimates rescaled so the gap sums to the metered register delta;
4. anything else stays MISSING. Estimates never overwrite valid actual reads.

    from ami_estimate import estimate_gaps, reconcile_to_register, consumption_drop_indicator
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ami_decisions import VeeConfig
from ami_validate import run_lengths


def _gap_ids(invalid: pd.Series) -> pd.Series:
    """Integer id per consecutive run of invalid rows (NaN for valid rows)."""
    starts = invalid & ~invalid.shift(fill_value=False)
    return starts.cumsum().where(invalid)


def _linear_fill(kwh: pd.Series, invalid: pd.Series, lengths: pd.Series,
                 max_len: int) -> pd.Series:
    """Linear interpolation for gaps with valid neighbours on both sides and length ≤ max_len."""
    if max_len <= 0:
        return pd.Series(np.nan, index=kwh.index)
    base = kwh.where(~invalid)
    filled = base.interpolate(method="linear", limit_area="inside")
    return filled.where(invalid & (lengths <= max_len))


def _day_type(local_ts: pd.Series) -> pd.Series:
    return np.where(local_ts.dt.dayofweek >= 5, "weekend", "weekday")


def _like_day_fill(df: pd.DataFrame, target: pd.Series, cfg: VeeConfig) -> pd.Series:
    """Mean of the same local wall-clock slot on the last ``like_days`` valid like days."""
    local = df["interval_start_utc"].dt.tz_convert(cfg.source_timezone)
    slot = local.dt.strftime("%H:%M")
    date = local.dt.normalize().dt.tz_localize(None)
    dtype = pd.Series(_day_type(local), index=df.index)
    valid = df["valid"] & df["kwh"].notna()
    history = pd.DataFrame({"date": date, "slot": slot, "dtype": dtype, "kwh": df["kwh"]})[valid]
    lookup = history.groupby(["slot", "dtype", "date"])["kwh"].mean()
    out = pd.Series(np.nan, index=df.index)
    for idx in target[target].index:
        try:
            cands = lookup.loc[(slot[idx], dtype[idx])]
        except KeyError:
            continue
        window = cands[(cands.index < date[idx]) &
                       (cands.index >= date[idx] - pd.Timedelta(days=cfg.like_day_lookback_days))]
        recent = window.sort_index().tail(cfg.like_days)
        if len(recent) >= 2:
            out[idx] = recent.mean()
    return out


def _prorate_register(df: pd.DataFrame, estimate: pd.Series,
                      invalid: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Rescale gap estimates so a register-bracketed gap sums to the register delta.

    The estimate supplies the shape; when any interval in the gap has no estimate the delta is
    spread uniformly instead. Either way the metered energy is conserved.
    """
    if "register_gap_total_kwh" not in df.columns:
        return estimate, pd.Series(False, index=df.index)
    scaled, prorated = estimate.copy(), pd.Series(False, index=df.index)
    for idx in df.index[df["register_gap_total_kwh"].notna()]:
        span = (df["interval_start_utc"] >= df.at[idx, "gap_start_utc"]) & (df.index <= idx)
        target = span & invalid
        if not target.any():
            continue
        actual = df.loc[span & ~invalid, "kwh"].sum()
        remaining = max(df.at[idx, "register_gap_total_kwh"] - actual, 0.0)
        shape = estimate[target]
        if shape.isna().any() or shape.sum() <= 0:
            shape = pd.Series(1.0, index=shape.index)
        scaled[target] = remaining * shape / shape.sum()
        prorated[target] = True
    return scaled, prorated


def estimate_gaps(df: pd.DataFrame, cfg: VeeConfig) -> pd.DataFrame:
    """Fill invalid / missing intervals per the configured rules; set ``quality_code``."""
    invalid = ~df["valid"]
    lengths = run_lengths(invalid)
    linear = _linear_fill(df["kwh"], invalid, lengths, cfg.linear_max_gap_intervals)
    like = pd.Series(np.nan, index=df.index)
    if cfg.long_gap_method == "like_day":
        long_gap = invalid & linear.isna() & (lengths <= cfg.max_estimation_gap_intervals)
        like = _like_day_fill(df, long_gap, cfg)
    estimate = linear.fillna(like)
    estimate, prorated = _prorate_register(df, estimate, invalid)
    code = np.select(
        [~invalid & df["flag_source_estimated"], ~invalid, prorated, linear.notna(), like.notna()],
        ["SOURCE_ESTIMATED", "ACTUAL", "ESTIMATED_REGISTER_PRORATED", "ESTIMATED_LINEAR",
         "ESTIMATED_LIKE_DAY"], default="MISSING")
    kwh = df["kwh"].where(~invalid, estimate)
    return df.assign(kwh=kwh, quality_code=code, gap_length_intervals=lengths)


def reconcile_to_register(intervals: pd.DataFrame, register: pd.DataFrame,
                          tolerance_pct: float) -> pd.DataFrame:
    """Compare interval sums to register deltas between consecutive register reads.

    ``intervals``: ``interval_start_utc``, ``kwh``. ``register``: ``instant_utc``,
    ``register_kwh`` (rollover already handled). Returns one row per register period.
    """
    reg = register.sort_values("instant_utc").reset_index(drop=True)
    periods = pd.DataFrame({"period_start_utc": reg["instant_utc"].shift(),
                            "period_end_utc": reg["instant_utc"],
                            "register_delta_kwh": reg["register_kwh"].diff()}).iloc[1:]
    sums = [intervals.loc[(intervals["interval_start_utc"] >= s) &
                          (intervals["interval_start_utc"] < e), "kwh"].sum(min_count=1)
            for s, e in zip(periods["period_start_utc"], periods["period_end_utc"])]
    out = periods.assign(interval_sum_kwh=sums)
    diff_pct = 100 * (out["interval_sum_kwh"] - out["register_delta_kwh"]) / out[
        "register_delta_kwh"].where(out["register_delta_kwh"] != 0)
    return out.assign(diff_pct=diff_pct, within_tolerance=diff_pct.abs() <= tolerance_pct)


def consumption_drop_indicator(df: pd.DataFrame, tz: str, *, recent_days: int = 30,
                               baseline_days: int = 90, ratio_threshold: float = 0.4,
                               min_baseline_kwh_per_day: float = 2.0) -> dict:
    """Sustained-drop indicator (possible bypass / tamper / vacancy). An indicator, not proof."""
    daily = (df.assign(d=df["interval_start_utc"].dt.tz_convert(tz).dt.date)
             .groupby("d")["kwh"].sum(min_count=1).dropna())
    if len(daily) < recent_days + baseline_days:
        return {"evaluated": False, "reason": "insufficient history"}
    recent = daily.iloc[-recent_days:].median()
    baseline = daily.iloc[-(recent_days + baseline_days):-recent_days].median()
    ratio = recent / baseline if baseline > 0 else np.nan
    flagged = bool(baseline >= min_baseline_kwh_per_day and ratio < ratio_threshold)
    return {"evaluated": True, "recent_median_kwh_per_day": float(recent),
            "baseline_median_kwh_per_day": float(baseline), "ratio": float(ratio),
            "flag_sustained_drop": flagged}
