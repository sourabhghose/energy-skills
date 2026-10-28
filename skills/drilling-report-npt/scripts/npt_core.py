"""NPT core: time-log normalization, 24-hour reconciliation, NPT flagging, aggregation, ILT.

Purpose: pure pandas logic behind the drilling-report-npt runner. No Spark, no network.

Usage:
    from npt_core import normalize_ops, reconcile_hours, flag_npt, aggregate_npt, compute_ilt
    ops = normalize_ops(raw, report_day_start_hour=6)
    recon = reconcile_hours(ops, report_day_start_hour=6)
    flagged = flag_npt(ops, text_cats, code_map, combine_mode="union", weather_policy="separate")
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from npt_taxonomy import COMBINE_MODES, classify_weather

REQUIRED_COLUMNS = ("well_id", "rig_id", "contractor", "start_time", "end_time",
                    "activity_code", "remarks")
TOLERANCE_HR = 0.01
MIN_ILT_SAMPLES = 5


def _check_columns(df: pd.DataFrame, required) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"time log is missing required columns: {missing}")


def _report_day(ts: pd.Series, start_hour: int) -> pd.Series:
    shifted = ts - pd.to_timedelta(start_hour, unit="h")
    return shifted.dt.tz_localize(None).dt.normalize() if shifted.dt.tz else shifted.dt.normalize()


def normalize_ops(raw: pd.DataFrame, report_day_start_hour: int) -> pd.DataFrame:
    """Typed copy of the time log with row_id, duration_hr, and report_day.

    Durations use elapsed time, so tz-aware timestamps give correct hours across DST.
    """
    _check_columns(raw, REQUIRED_COLUMNS)
    start = pd.to_datetime(raw["start_time"])
    end = pd.to_datetime(raw["end_time"])
    duration = (end - start).dt.total_seconds() / 3600.0
    row_id = raw["row_id"].astype(str) if "row_id" in raw.columns else pd.Series(
        [f"r{i}" for i in range(len(raw))], index=raw.index)
    return raw.assign(
        row_id=row_id, start_time=start, end_time=end,
        activity_code=raw["activity_code"].astype("string").str.strip(),
        duration_hr=duration, report_day=_report_day(start, report_day_start_hour),
    )


def _expected_day_hours(day: pd.Timestamp, tz, start_hour: int) -> float:
    """Elapsed hours in the reporting day: 23 or 25 on DST transition days when tz-aware."""
    if tz is None:
        return 24.0
    begin = (day + pd.Timedelta(hours=start_hour)).tz_localize(tz, nonexistent="shift_forward")
    finish = (day + pd.Timedelta(days=1, hours=start_hour)).tz_localize(tz, nonexistent="shift_forward")
    return (finish - begin).total_seconds() / 3600.0


def _gaps_overlaps(group: pd.DataFrame) -> tuple[float, float]:
    g = group.sort_values("start_time")
    prev_end = g["end_time"].shift(1)
    delta = (g["start_time"] - prev_end).dt.total_seconds().div(3600.0).dropna()
    return float(delta[delta > 0].sum()), float(-delta[delta < 0].sum())


def reconcile_hours(ops: pd.DataFrame, report_day_start_hour: int) -> pd.DataFrame:
    """Per well and report day: logged vs expected hours, internal gaps and overlaps."""
    tz = ops["start_time"].dt.tz
    rows = []
    for (well, day), group in ops.groupby(["well_id", "report_day"], sort=True):
        gap, overlap = _gaps_overlaps(group)
        logged = float(group["duration_hr"].sum())
        expected = _expected_day_hours(pd.Timestamp(day), tz, report_day_start_hour)
        rows.append({"well_id": well, "report_day": day, "logged_hr": round(logged, 3),
                     "expected_hr": expected, "internal_gap_hr": round(gap, 3),
                     "overlap_hr": round(overlap, 3), "negative_rows": int((group["duration_hr"] < 0).sum())})
    recon = pd.DataFrame(rows)
    if recon.empty:
        return recon
    diff = recon["logged_hr"] - recon["expected_hr"]
    status = np.select(
        [recon["negative_rows"] > 0, recon["overlap_hr"] > TOLERANCE_HR, diff < -TOLERANCE_HR,
         diff > TOLERANCE_HR],
        ["negative_duration", "overlap", "short_day", "long_day"], default="ok")
    return recon.assign(diff_hr=diff.round(3), status=status)


def _code_categories(ops: pd.DataFrame, code_map: dict) -> tuple[pd.Series, pd.Series]:
    codes = ops["activity_code"].astype("string")
    mapped = codes.map(lambda c: code_map.get(str(c)) if pd.notna(c) else None)
    unmapped = codes.map(lambda c: pd.notna(c) and str(c) not in code_map)
    return mapped.astype(object).where(mapped.notna(), None), unmapped.astype(bool)


def _combine(code_cat, text_cat, mode: str):
    if mode == "code_only":
        return code_cat, "code" if code_cat else None
    if mode == "text_only":
        return text_cat, "text" if text_cat else None
    if mode == "intersection":
        return (code_cat, "both") if code_cat and text_cat else (None, None)
    if code_cat and text_cat:
        return code_cat, "both"
    if code_cat:
        return code_cat, "code"
    return (text_cat, "text") if text_cat else (None, None)


def flag_npt(ops: pd.DataFrame, text_cats: pd.DataFrame, code_map: dict,
             combine_mode: str, weather_policy: str) -> pd.DataFrame:
    """Row-level NPT flags. Coded category wins when both sources agree a row is NPT."""
    if combine_mode not in COMBINE_MODES:
        raise ValueError(f"combine_mode must be one of {COMBINE_MODES}")
    code_cat, unmapped = _code_categories(ops, code_map)
    merged = ops.assign(code_category=code_cat, unmapped_code=unmapped).merge(
        text_cats, on="row_id", how="left")
    text_col = merged["text_category"].astype(object).where(merged["text_category"].notna(), None)
    combined = [_combine(c, t, combine_mode) for c, t in zip(merged["code_category"], text_col)]
    applied = [classify_weather(cat, weather_policy) for cat, _ in combined]
    return merged.assign(
        text_category=text_col,
        npt_category=[a[0] for a in applied],
        npt_source=[src if a[0] else None for (_, src), a in zip(combined, applied)],
        weather_downtime=[a[1] for a in applied],
        is_npt=[a[0] is not None for a in applied],
    )


def aggregate_npt(flagged: pd.DataFrame, by: list[str], weather_policy: str) -> pd.DataFrame:
    """NPT hours and NPT % of logged time by the given keys (e.g. ['rig_id','npt_category'])."""
    keys = [k for k in by if k != "npt_category"]
    total = flagged.groupby(keys, dropna=False)["duration_hr"].sum().rename("total_hr") if keys else None
    npt = flagged[flagged["is_npt"]]
    out = npt.groupby(by, dropna=False)["duration_hr"].sum().rename("npt_hr").reset_index()
    if weather_policy == "separate":
        wx_rows = flagged[flagged["weather_downtime"]]
        if keys:
            wx = wx_rows.groupby(keys, dropna=False)["duration_hr"].sum().rename("weather_downtime_hr")
            out = out.merge(wx.reset_index(), on=keys, how="outer")
        else:
            out = out.assign(weather_downtime_hr=float(wx_rows["duration_hr"].sum()))
    if total is not None:
        out = out.merge(total.reset_index(), on=keys, how="left")
        out = out.assign(npt_pct=(100.0 * out["npt_hr"].fillna(0) / out["total_hr"]).round(2))
    return out.sort_values(by).reset_index(drop=True)


def evidence_table(flagged: pd.DataFrame) -> pd.DataFrame:
    """Shareable evidence: one row per NPT time-log row with source and verbatim quote."""
    cols = ["row_id", "well_id", "rig_id", "contractor", "report_day", "start_time", "end_time",
            "duration_hr", "activity_code", "npt_category", "npt_source", "text_quote"]
    present = [c for c in cols if c in flagged.columns]
    return flagged.loc[flagged["is_npt"], present].reset_index(drop=True)


def _benchmark_value(series: pd.Series, benchmark: str, higher_is_better: bool) -> float:
    q = {"p10": 0.10, "p25": 0.25}[benchmark]
    return float(series.quantile(1 - q if higher_is_better else q))


def _ilt_group(group: pd.DataFrame, benchmark: str) -> pd.Series:
    if len(group) < MIN_ILT_SAMPLES:
        return pd.Series(np.nan, index=group.index)
    if "footage_ft" in group and group["footage_ft"].fillna(0).gt(0).all():
        rate = group["footage_ft"] / group["duration_hr"]
        best = _benchmark_value(rate, benchmark, higher_is_better=True)
        return (group["duration_hr"] - group["footage_ft"] / best).clip(lower=0)
    best = _benchmark_value(group["duration_hr"], benchmark, higher_is_better=False)
    return (group["duration_hr"] - best).clip(lower=0)


def compute_ilt(flagged: pd.DataFrame, benchmark: str, group_cols: list[str],
                technical_limits: pd.DataFrame | None = None) -> pd.DataFrame:
    """Invisible lost time on productive rows vs a benchmark (offset percentile or tech limit).

    Groups with fewer than MIN_ILT_SAMPLES rows get NaN ILT (too few offsets to benchmark).
    `technical_limit` needs a table keyed by `group_cols` with `tl_duration_hr`.
    """
    productive = flagged[~flagged["is_npt"] & ~flagged["weather_downtime"]]
    if benchmark == "none" or productive.empty:
        return productive.assign(ilt_hr=np.nan)
    if benchmark == "technical_limit":
        if technical_limits is None:
            raise ValueError("ilt_benchmark='technical_limit' needs a technical_limits table")
        merged = productive.merge(technical_limits, on=group_cols, how="left")
        return merged.assign(ilt_hr=(merged["duration_hr"] - merged["tl_duration_hr"]).clip(lower=0))
    parts = [_ilt_group(g, benchmark) for _, g in productive.groupby(group_cols, dropna=False)]
    ilt = pd.concat(parts) if parts else pd.Series(dtype=float)
    return productive.assign(ilt_hr=ilt.reindex(productive.index))
