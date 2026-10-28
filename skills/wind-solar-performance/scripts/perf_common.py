"""Shared primitives for wind and solar performance: decisions, time handling, energy integration.

Pure pandas/numpy. Timestamps must be timezone-aware; the interval convention is a decision.
"""

from __future__ import annotations

import pandas as pd

TIMESTAMP_CONVENTIONS = ("interval_beginning", "interval_ending")


class DecisionRequired(ValueError):
    """A decision point that belongs to the user was not supplied."""

    def __init__(self, name: str, options, why: str = ""):
        self.name, self.options = name, list(options)
        super().__init__(f"Decision required: {name!r}; choose one of {self.options}. {why}".strip())


def require(name: str, value, options, why: str = ""):
    if value is None or value not in options:
        raise DecisionRequired(name, options, why)
    return value


def infer_interval(ts: pd.Series) -> pd.Timedelta:
    """Median spacing of a timestamp series (per-device series should be passed)."""
    diffs = ts.sort_values().diff().dropna()
    if diffs.empty:
        raise ValueError("Need at least two timestamps to infer the interval length")
    return diffs.median()


def with_interval_start(df: pd.DataFrame, convention: str, ts_col: str = "timestamp",
                        group_col: str | None = None) -> pd.DataFrame:
    """Add `interval_start` and `interval_h`; reject naive timestamps."""
    require("timestamp_convention", convention, TIMESTAMP_CONVENTIONS)
    ts = pd.to_datetime(df[ts_col])
    if ts.dt.tz is None:
        raise ValueError(f"{ts_col} must be timezone-aware (state the site's timezone or UTC)")
    step = infer_interval(ts if group_col is None else ts[df[group_col] == df[group_col].iloc[0]])
    start = ts - step if convention == "interval_ending" else ts
    return df.assign(**{ts_col: ts, "interval_start": start, "interval_h": step / pd.Timedelta(hours=1)})


def energy_kwh(power_kw: pd.Series, interval_h: pd.Series | float) -> pd.Series:
    return power_kw * interval_h
