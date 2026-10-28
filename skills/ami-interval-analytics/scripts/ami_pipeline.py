"""End-to-end VEE for one meter or a whole frame, plus the read-only preview profile.

Pure pandas; the Databricks runner (``ami_run.py``) applies ``vee_meter`` per meter with
``groupBy(meter).applyInPandas`` so the same tested code runs at scale.

    from ami_pipeline import vee_frame, preview_profile, vee_summary
    out = vee_frame(raw, cfg)                 # raw: meter_id, read_ts, value[, quality]
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ami_decisions import VeeConfig
from ami_estimate import estimate_gaps
from ami_time import expected_intervals_per_local_day, label_instants_utc, to_interval_start_utc
from ami_validate import (detect_interval_minutes, detect_read_type, register_to_interval,
                          reindex_to_grid, run_lengths, validate_intervals)

OUTPUT_COLUMNS = ["meter_id", "interval_start_utc", "interval_start_local", "local_date",
                  "raw_kwh", "kwh", "quality_code", "flags", "gap_length_intervals"]
OUTPUT_SCHEMA = ("meter_id string, interval_start_utc timestamp, interval_start_local string, "
                 "local_date date, raw_kwh double, kwh double, quality_code string, "
                 "flags string, gap_length_intervals int")


def _canonical_interval(raw: pd.DataFrame, cfg: VeeConfig) -> pd.DataFrame:
    times = to_interval_start_utc(raw["read_ts"], cfg.source_timezone, cfg.timestamp_basis,
                                  cfg.interval_convention, cfg.interval_minutes)
    return pd.DataFrame({"interval_start_utc": times["interval_start_utc"],
                         "kwh": pd.to_numeric(raw["value"], errors="coerce"),
                         "source_quality": raw.get("quality"),
                         "flag_dst_ambiguous_single": times["flag_dst_ambiguous_single"],
                         "flag_nonexistent_time": times["flag_nonexistent_time"]})


def _canonical_register(raw: pd.DataFrame, cfg: VeeConfig) -> pd.DataFrame:
    inst = label_instants_utc(raw["read_ts"], cfg.source_timezone, cfg.timestamp_basis)
    reads = pd.DataFrame({"instant_utc": inst["instant_utc"],
                          "register_kwh": pd.to_numeric(raw["value"], errors="coerce")}).dropna()
    out = register_to_interval(reads, cfg.interval_minutes, cfg.register_rollover_kwh)
    return out.assign(source_quality=None, flag_dst_ambiguous_single=False,
                      flag_nonexistent_time=False)


def _flags_string(df: pd.DataFrame) -> pd.Series:
    flag_cols = [c for c in df.columns if c.startswith("flag_") and df[c].any()]
    if not flag_cols:
        return pd.Series("", index=df.index)
    names = np.array([c.removeprefix("flag_") for c in flag_cols])
    matrix = df[flag_cols].to_numpy(dtype=bool)
    return pd.Series(["|".join(names[row]) for row in matrix], index=df.index)


def vee_meter(raw: pd.DataFrame, cfg: VeeConfig) -> pd.DataFrame:
    """Validate and estimate one meter. ``raw`` columns: meter_id, read_ts, value[, quality]."""
    meter_id = str(raw["meter_id"].iloc[0])
    cfg = cfg.for_meter(meter_id)
    builder = _canonical_register if cfg.read_type == "register" else _canonical_interval
    canonical = builder(raw.reset_index(drop=True), cfg)
    gridded = reindex_to_grid(canonical, cfg.interval_minutes)
    if gridded.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    estimated = estimate_gaps(validate_intervals(gridded, cfg), cfg)
    local = estimated["interval_start_utc"].dt.tz_convert(cfg.source_timezone)
    return pd.DataFrame({
        "meter_id": meter_id,
        "interval_start_utc": estimated["interval_start_utc"],
        "interval_start_local": local.dt.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "local_date": local.dt.date,
        "raw_kwh": estimated["raw_kwh"],
        "kwh": estimated["kwh"],
        "quality_code": estimated["quality_code"],
        "flags": _flags_string(estimated),
        "gap_length_intervals": estimated["gap_length_intervals"].astype("int32"),
    })


def vee_frame(raw: pd.DataFrame, cfg: VeeConfig) -> pd.DataFrame:
    """Run ``vee_meter`` for every meter (record order within a meter is preserved)."""
    parts = [vee_meter(group, cfg) for _, group in raw.groupby("meter_id", sort=True)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=OUTPUT_COLUMNS)


def vee_summary(validated: pd.DataFrame, cfg: VeeConfig) -> pd.DataFrame:
    """One row per meter: completeness against DST-aware expected counts, codes, flags."""
    expected = expected_intervals_per_local_day(validated["local_date"], cfg.source_timezone,
                                                cfg.interval_minutes)
    days = validated.assign(expected=expected).groupby(["meter_id", "local_date"])["expected"]
    per_meter_expected = days.first().groupby("meter_id").sum()
    codes = pd.crosstab(validated["meter_id"], validated["quality_code"])
    flags = validated["flags"].str.get_dummies(sep="|").groupby(validated["meter_id"]).sum()
    summary = codes.join(flags.add_prefix("flag_"), how="left").fillna(0).astype(int)
    summary = summary.assign(intervals_out=validated.groupby("meter_id").size(),
                             intervals_expected_full_days=per_meter_expected,
                             total_kwh=validated.groupby("meter_id")["kwh"].sum())
    actual = summary.get("ACTUAL", 0) + summary.get("SOURCE_ESTIMATED", 0)
    return summary.assign(actual_pct=100 * actual / summary["intervals_out"]).reset_index()


def _gap_histogram(gaps: pd.Series) -> dict[str, int]:
    bins = [0, 1, 2, 4, 8, 16, 96, 288, np.inf]
    labels = ["1", "2", "3-4", "5-8", "9-16", "17-96", "97-288", ">288"]
    cut = pd.cut(gaps, bins=bins, labels=labels)
    return {str(k): int(v) for k, v in cut.value_counts().sort_index().items()}


def _naive_gaps(raw: pd.DataFrame, interval_minutes: int) -> pd.Series:
    lengths = []
    step = pd.Timedelta(minutes=interval_minutes)
    for _, g in raw.groupby("meter_id"):
        ts = pd.to_datetime(g["read_ts"], utc=False).sort_values().drop_duplicates()
        missing = (ts.diff() / step).dropna() - 1
        lengths.extend(missing[missing > 0].round().astype(int).tolist())
    return pd.Series(lengths, dtype=int)


def preview_profile(raw: pd.DataFrame, source_timezone: str | None = None,
                    spike_candidates_kw: tuple[float, ...] = (12.0, 24.0, 48.0, 96.0)) -> dict:
    """Read-only profile that surfaces each decision with its effect on this data."""
    ts = pd.to_datetime(raw["read_ts"], utc=False)
    first = raw.groupby("meter_id", sort=False).head(5000)
    interval = detect_interval_minutes(pd.to_datetime(first["read_ts"]).drop_duplicates())
    values = pd.to_numeric(raw["value"], errors="coerce")
    read_type = detect_read_type(raw.groupby("meter_id").head(500)["value"])
    hours = interval / 60.0
    dup = raw.assign(ts=ts).duplicated(["meter_id", "ts"]).sum()
    gaps = _naive_gaps(raw, interval)
    profile = {
        "rows": int(len(raw)), "meters": int(raw["meter_id"].nunique()),
        "detected_interval_minutes": interval, "detected_read_type": read_type,
        "timestamps_tz_aware": ts.dt.tz is not None,
        "duplicate_labels": int(dup),
        "negative_values": int((values < 0).sum()),
        "zero_values": int((values == 0).sum()),
        "gap_runs_by_length_intervals": _gap_histogram(gaps),
        "intervals_in_gaps_by_linear_limit": {
            str(k): int(gaps[gaps <= k].sum()) for k in (2, 4, 8)},
        "intervals_in_gaps_over_24h": int(gaps[gaps * hours > 24].sum()),
        "spike_counts_by_kw_ceiling": {
            str(kw): int((values / hours > kw).sum()) for kw in spike_candidates_kw},
        "quality_codes": (raw["quality"].astype(str).value_counts().to_dict()
                          if "quality" in raw.columns else {}),
    }
    return {**profile, **_dst_profile(raw, source_timezone, interval)}


def _dst_profile(raw: pd.DataFrame, tz: str | None, interval: int) -> dict:
    if tz is None:
        return {"dst_check": "source_timezone not given; DST duplicates not assessed"}
    if pd.to_datetime(raw["read_ts"]).dt.tz is not None:
        return {"dst_check": "timestamps carry offsets; DST already explicit"}
    flags = [label_instants_utc(g["read_ts"].reset_index(drop=True), tz, "local_naive")
             for _, g in raw.groupby("meter_id")]
    joined = pd.concat(flags, ignore_index=True)
    return {"dst_check": "assessed as local_naive",
            "dst_fall_back_single_labels": int(joined["flag_dst_ambiguous_single"].sum()),
            "dst_spring_forward_nonexistent_labels": int(joined["flag_nonexistent_time"].sum())}


__all__ = ["vee_meter", "vee_frame", "vee_summary", "preview_profile", "OUTPUT_SCHEMA",
           "OUTPUT_COLUMNS", "run_lengths"]
