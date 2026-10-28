"""Operating-state filtering and condition features for rotating equipment.

Purpose: decide which grid rows describe steady running (the only rows where condition
signals are comparable), then compute rolling features and vibration zones.
  * running: from a run-status tag, or from a threshold on one measurement
  * transients: rows within N minutes after a start or before a stop are excluded
  * features: rolling mean / std / slope per measurement, current coefficient of variation
    (ESP gas interference / unstable loading), motor temperature rise over intake, vibration
    zone per ISO 10816-3 style boundaries

Usage:
    from features import operating_state, add_features
    wide = operating_state(wide, running_definition="status_tag", transient_exclusion_minutes=30)
    feats = add_features(wide, window="2h", zone_boundaries=(2.3, 4.5, 7.1))
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pdm_taxonomy import RUNNING_DEFINITIONS, vibration_zone

SIGNAL_COLUMNS_EXCLUDED = {"asset_id", "ts", "running", "steady", "run_status"}


def _running(wide: pd.DataFrame, definition: str, threshold: dict | None) -> pd.Series:
    if definition == "status_tag":
        if "run_status" not in wide:
            raise ValueError("running_definition='status_tag' needs a run_status tag in the tag map")
        return wide["run_status"].eq(1.0)
    if not threshold or threshold.get("measurement") not in wide:
        raise ValueError("running_definition='threshold' needs threshold={'measurement': ..., 'min': ...}")
    return wide[threshold["measurement"]].gt(float(threshold["min"]))


def _near_transition(ts: pd.Series, running: pd.Series, minutes: int) -> pd.Series:
    """True for running rows within `minutes` after a start or before a stop."""
    change = running.ne(running.shift(1)) & running.shift(1).notna()
    starts = ts[change & running]
    stops = ts[change & ~running]
    window = pd.Timedelta(minutes=minutes)
    near = pd.Series(False, index=ts.index)
    for t in starts:
        near |= (ts >= t) & (ts < t + window)
    for t in stops:
        near |= (ts < t) & (ts >= t - window)
    return near


def operating_state(wide: pd.DataFrame, running_definition: str, transient_exclusion_minutes: int,
                    threshold: dict | None = None) -> pd.DataFrame:
    """Adds `running` and `steady` (running and not near a start/stop) per asset."""
    if running_definition not in RUNNING_DEFINITIONS:
        raise ValueError(f"running_definition must be one of {RUNNING_DEFINITIONS}")
    parts = []
    for _, g in wide.sort_values(["asset_id", "ts"]).groupby("asset_id", sort=False):
        running = _running(g, running_definition, threshold).fillna(False).astype(bool)
        near = _near_transition(g["ts"], running, int(transient_exclusion_minutes))
        parts.append(g.assign(running=running, steady=running & ~near))
    return pd.concat(parts) if parts else wide.assign(running=False, steady=False)


def _slope_per_hour(series: pd.Series, window: str) -> pd.Series:
    t_hours = (series.index - series.index[0]).total_seconds() / 3600.0
    s = pd.Series(series.to_numpy(dtype=float), index=series.index)
    tt = pd.Series(t_hours, index=series.index).where(s.notna())  # same rows as the signal
    roll = lambda x: x.rolling(window, min_periods=3)  # noqa: E731
    cov = roll(s * tt).mean() - roll(s).mean() * roll(tt).mean()
    var = roll(tt * tt).mean() - roll(tt).mean() ** 2
    return cov / var.where(var > 0)


def _asset_features(g: pd.DataFrame, signals: list[str], window: str) -> pd.DataFrame:
    indexed = g.set_index("ts")
    steady = indexed[signals].where(indexed["steady"].astype(bool), axis=0)
    out = {}
    for col in signals:
        roll = steady[col].rolling(window, min_periods=3)
        out[f"{col}_mean"] = roll.mean()
        out[f"{col}_std"] = roll.std()
        out[f"{col}_slope_per_h"] = _slope_per_hour(steady[col], window)
    feats = pd.DataFrame(out, index=steady.index)
    if "motor_current" in signals:
        feats["motor_current_cv"] = feats["motor_current_std"] / feats["motor_current_mean"].where(
            feats["motor_current_mean"] > 0)
    if {"motor_temperature", "intake_temperature"} <= set(signals):
        feats["motor_temp_rise"] = steady["motor_temperature"] - steady["intake_temperature"]
    feats = feats.where(indexed["steady"].astype(bool), axis=0)  # features only describe steady rows
    return feats.reset_index().assign(asset_id=g["asset_id"].iloc[0], steady=g["steady"].to_numpy())


def add_features(wide: pd.DataFrame, window: str, zone_boundaries: tuple[float, float, float] | None) -> pd.DataFrame:
    """Rolling features on steady rows only; non-steady rows keep NaN features."""
    signals = [c for c in wide.columns if c not in SIGNAL_COLUMNS_EXCLUDED and wide[c].dtype.kind in "fi"]
    parts = [_asset_features(g, signals, window) for _, g in wide.groupby("asset_id", sort=True)]
    feats = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if zone_boundaries and "vibration_velocity_mean" in feats:
        feats = feats.assign(vibration_zone=feats["vibration_velocity_mean"].map(
            lambda v: vibration_zone(v, zone_boundaries)))
    return feats.replace([np.inf, -np.inf], np.nan)
