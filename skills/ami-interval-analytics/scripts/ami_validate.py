"""Validation rules for AMI interval data (the V in VEE). Pure pandas, one meter at a time.

Input frame (one meter, canonical columns): ``interval_start_utc`` (tz-aware UTC), ``kwh``
(float, may be NaN), optional ``source_quality`` (``'A'`` actual / ``'E'`` estimated by the
head-end or MDM). Output adds boolean ``flag_*`` columns and ``valid``.

    from ami_validate import detect_read_type, register_to_interval, validate_intervals
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ami_decisions import VeeConfig

SOURCE_ESTIMATED_CODES = {"E", "EST", "ESTIMATED", "S"}


def run_lengths(mask: pd.Series) -> pd.Series:
    """For each True element, the length of the consecutive True run it belongs to (else 0)."""
    mask = mask.fillna(False).astype(bool)
    run_id = (mask != mask.shift(fill_value=False)).cumsum()
    lengths = mask.groupby(run_id).transform("sum")
    return lengths.where(mask, 0).astype(int)


def detect_read_type(values: pd.Series) -> str:
    """Guess ``'register'`` (cumulative dial) vs ``'interval'`` from the value shape."""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) < 10:
        return "interval"
    diffs = clean.diff().dropna()
    non_decreasing = (diffs >= 0).mean()
    scale = clean.median() / max(diffs.abs().median(), 1e-9)
    return "register" if non_decreasing >= 0.98 and scale > 50 else "interval"


def detect_interval_minutes(instants: pd.Series) -> int:
    """Most common spacing between consecutive timestamps, in minutes."""
    diffs = instants.sort_values().diff().dropna().dt.total_seconds() / 60.0
    diffs = diffs[diffs > 0]
    if diffs.empty:
        raise ValueError("Cannot detect interval: fewer than two distinct timestamps.")
    return int(diffs.round().mode().iloc[0])


def register_to_interval(reads: pd.DataFrame, interval_minutes: int,
                         rollover_kwh: float) -> pd.DataFrame:
    """Convert cumulative register reads to interval kWh.

    ``reads``: one meter, columns ``instant_utc`` (read time) and ``register_kwh``. Each
    interval starts at the previous read. A negative delta near the dial capacity is a
    rollover (``delta + rollover_kwh``); any other negative delta is a meter reset/exchange
    and is left NaN. A delta spanning a gap is kept as ``register_gap_total_kwh`` so the
    estimator can make the gap's estimates sum to the metered energy.
    """
    ordered = reads.sort_values("instant_utc").reset_index(drop=True)
    prev_value = ordered["register_kwh"].shift()
    prev_time = ordered["instant_utc"].shift()
    delta = ordered["register_kwh"] - prev_value
    rollover = (delta < 0) & (prev_value >= 0.9 * rollover_kwh) & (
        ordered["register_kwh"] <= 0.1 * rollover_kwh)
    reset = (delta < 0) & ~rollover
    delta = delta.where(~rollover, delta + rollover_kwh).where(~reset)
    step = pd.Timedelta(minutes=interval_minutes)
    consecutive = (ordered["instant_utc"] - prev_time) == step
    out = pd.DataFrame({
        "interval_start_utc": ordered["instant_utc"] - step,
        "kwh": delta.where(consecutive),
        "register_gap_total_kwh": delta.where(~consecutive & prev_time.notna()),
        "gap_start_utc": prev_time.where(~consecutive),
        "flag_register_rollover": rollover,
        "flag_register_reset": reset,
    })
    return out.iloc[1:].reset_index(drop=True)


def _flag_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    dup_key = df.duplicated("interval_start_utc", keep=False)
    conflict = dup_key & df.groupby("interval_start_utc")["kwh"].transform("nunique").gt(1)
    keep = ~df.duplicated("interval_start_utc", keep="first")
    flagged = df.assign(flag_duplicate=dup_key, flag_duplicate_conflict=conflict)
    return flagged[keep].reset_index(drop=True)


def reindex_to_grid(df: pd.DataFrame, interval_minutes: int) -> pd.DataFrame:
    """Deduplicate and reindex one meter onto the full expected grid; add ``flag_missing``."""
    deduped = _flag_duplicates(df.dropna(subset=["interval_start_utc"]))
    if deduped.empty:
        return deduped.assign(flag_missing=pd.Series(dtype=bool))
    grid = pd.date_range(deduped["interval_start_utc"].min(), deduped["interval_start_utc"].max(),
                         freq=f"{interval_minutes}min", tz="UTC", name="interval_start_utc")
    full = deduped.set_index("interval_start_utc").reindex(grid).reset_index()
    flag_cols = [c for c in full.columns if c.startswith("flag_")]
    full[flag_cols] = full[flag_cols].astype("boolean").fillna(False).astype(bool)
    return full.assign(flag_missing=full["kwh"].isna())


def _flag_values(df: pd.DataFrame, cfg: VeeConfig) -> dict[str, pd.Series]:
    kwh = df["kwh"]
    kw = kwh / cfg.interval_hours
    negative = kwh < 0
    p99 = kwh[kwh > 0].quantile(0.99) if (kwh > 0).any() else np.nan
    zero_run = run_lengths(kwh == 0) * cfg.interval_hours
    value_run = (kwh != kwh.shift()).cumsum()
    flat_run = kwh.groupby(value_run).transform("size").where((kwh != 0) & kwh.notna(), 0)
    quality = df.get("source_quality", pd.Series(index=df.index, dtype=object))
    return {
        "flag_negative_export": negative & (cfg.net_metering_policy == "negative_is_export"),
        "flag_negative_error": negative & (cfg.net_metering_policy == "negative_is_error"),
        "flag_spike": kw.abs() > cfg.spike_max_kw,
        "flag_spike_suspect": (kwh > 10 * p99) & (kw.abs() <= cfg.spike_max_kw),
        "flag_extended_zero": zero_run >= cfg.extended_zero_hours,
        "flag_flatline": flat_run * cfg.interval_hours >= cfg.flatline_min_hours,
        "flag_source_estimated": quality.astype(str).str.upper().isin(SOURCE_ESTIMATED_CODES),
    }


INVALIDATING = ("flag_missing", "flag_negative_error", "flag_spike", "flag_flatline",
                "flag_nonexistent_time", "flag_duplicate_conflict", "flag_register_reset")


def validate_intervals(df: pd.DataFrame, cfg: VeeConfig) -> pd.DataFrame:
    """Apply value rules to a gridded meter frame; add flags and ``valid``.

    Suspect-only flags (spike_suspect, extended_zero, negative_export, source_estimated,
    dst_ambiguous_single) are reported but do not invalidate the read.
    """
    flags = _flag_values(df, cfg)
    out = df.assign(**{k: v.fillna(False).astype(bool) for k, v in flags.items()})
    present = [c for c in INVALIDATING if c in out.columns]
    invalid = out[present].any(axis=1)
    return out.assign(valid=~invalid, raw_kwh=df["kwh"])
