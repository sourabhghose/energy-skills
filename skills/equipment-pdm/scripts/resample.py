"""Resample irregular historian samples onto a regular grid with explicit gap limits.

Purpose: historians store exception/compression-filtered samples at irregular times. Naive
`resample().interpolate()` bridges outages of hours or days with a straight line. Here each
grid point is filled only when the bracketing raw samples are no further apart than
`max_gap`:
  * analog + "linear": time-weighted interpolation between bracketing samples
  * analog + "step":   last value held (PI "step" tags, setpoints)
  * state tags:        always step, held until the next recorded change (no gap limit)

Usage:
    from resample import resample_grid
    wide = resample_grid(samples, freq="10min", analog_interpolation="linear", max_gap="30min")
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pdm_taxonomy import ANALOG_INTERPOLATIONS, MEASUREMENTS


def _bracket(grid: pd.DatetimeIndex, raw: pd.DataFrame) -> pd.DataFrame:
    g = pd.DataFrame({"ts": grid})
    r = raw[["ts", "value"]].sort_values("ts")
    prev = pd.merge_asof(g, r.rename(columns={"value": "prev_val"}).assign(prev_ts=r["ts"]),
                         on="ts", direction="backward")
    nxt = pd.merge_asof(g, r.rename(columns={"value": "next_val"}).assign(next_ts=r["ts"]),
                        on="ts", direction="forward")
    return prev.assign(next_ts=nxt["next_ts"].to_numpy(), next_val=nxt["next_val"].to_numpy())


def _fill(b: pd.DataFrame, method: str, max_gap: pd.Timedelta, is_state: bool) -> np.ndarray:
    exact = b["prev_ts"] == b["ts"]
    if is_state:
        return b["prev_val"].to_numpy(dtype=float)
    span = b["next_ts"] - b["prev_ts"]
    since = b["ts"] - b["prev_ts"]
    if method == "step":
        ok = exact | (span <= max_gap) | (b["next_ts"].isna() & (since <= max_gap))
        return b["prev_val"].where(ok).to_numpy(dtype=float)
    frac = (since / span.where(span > pd.Timedelta(0))).astype(float)
    interp = b["prev_val"] + frac * (b["next_val"] - b["prev_val"])
    ok = span <= max_gap
    return interp.where(ok).where(~exact, b["prev_val"]).to_numpy(dtype=float)


def resample_series(raw: pd.DataFrame, grid: pd.DatetimeIndex, method: str, max_gap: pd.Timedelta,
                    is_state: bool) -> pd.Series:
    """One measurement of one asset on the grid."""
    return pd.Series(_fill(_bracket(grid, raw), method, max_gap, is_state), index=grid)


def resample_grid(samples: pd.DataFrame, freq: str, analog_interpolation: str, max_gap: str) -> pd.DataFrame:
    """Wide frame: one row per (asset_id, ts), one column per measurement."""
    if analog_interpolation not in ANALOG_INTERPOLATIONS:
        raise ValueError(f"analog_interpolation must be one of {ANALOG_INTERPOLATIONS}")
    gap = pd.Timedelta(max_gap)
    frames = []
    for asset, group in samples.groupby("asset_id", sort=True):
        grid = pd.date_range(group["ts"].min().floor(freq), group["ts"].max().ceil(freq), freq=freq)
        cols = {m: resample_series(g, grid, analog_interpolation, gap, MEASUREMENTS[m][1] == "state")
                for m, g in group.groupby("measurement")}
        frames.append(pd.DataFrame(cols, index=grid).rename_axis("ts").reset_index().assign(asset_id=asset))
    if not frames:
        return pd.DataFrame(columns=["asset_id", "ts"])
    wide = pd.concat(frames, ignore_index=True)
    return wide[["asset_id", "ts", *[c for c in wide.columns if c not in ("asset_id", "ts")]]]
