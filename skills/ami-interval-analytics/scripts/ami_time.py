"""Timezone, DST, and interval-convention handling for AMI interval data (pure pandas).

Converts meter timestamps to ``interval_start_utc`` (interval-beginning, UTC), resolving the
repeated fall-back hour by record order and flagging labels that cannot exist (spring-forward
gap). Also builds the expected interval grid and per-local-day expected counts (92 / 96 / 100
intervals for 23 / 24 / 25-hour days at 15 minutes).

    from ami_time import to_interval_start_utc, expected_grid, expected_intervals_per_local_day
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _localize_naive(labels: pd.Series, tz: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Localize naive wall-clock labels; return (utc, ambiguous_single, nonexistent) masks."""
    n = len(labels)
    as_dst = labels.dt.tz_localize(tz, ambiguous=np.ones(n, dtype=bool), nonexistent="NaT")
    as_std = labels.dt.tz_localize(tz, ambiguous=np.zeros(n, dtype=bool), nonexistent="NaT")
    nonexistent = labels.notna() & as_dst.isna()
    ambiguous = as_dst.notna() & as_std.notna() & (as_dst != as_std)
    # Fall-back hour: first occurrence of a wall-clock label is DST, the second is standard.
    amb_labels = labels[ambiguous]
    occurrence = pd.Series(-1, index=labels.index)
    occurrence[ambiguous] = amb_labels.groupby(amb_labels).cumcount()
    counts = pd.Series(0, index=labels.index)
    counts[ambiguous] = amb_labels.map(amb_labels.value_counts())
    is_dst = ~ambiguous | (occurrence == 0)
    resolved = labels.dt.tz_localize(tz, ambiguous=is_dst.to_numpy(), nonexistent="NaT")
    ambiguous_single = ambiguous & (counts == 1)
    return resolved.dt.tz_convert("UTC"), ambiguous_single, nonexistent


def label_instants_utc(labels: pd.Series, tz: str, basis: str) -> pd.DataFrame:
    """Return UTC instants for ``labels`` plus DST flags.

    ``labels`` must be in record order for one meter (the fall-back hour is resolved by order).
    Columns: ``instant_utc``, ``flag_dst_ambiguous_single``, ``flag_nonexistent_time``.
    """
    parsed = pd.to_datetime(labels, utc=(basis == "offset_aware"))
    false = pd.Series(False, index=labels.index)
    if basis == "local_naive":
        if parsed.dt.tz is not None:
            raise ValueError("timestamp_basis='local_naive' but timestamps carry a timezone.")
        utc, single, nonexistent = _localize_naive(parsed, tz)
    elif basis == "utc":
        utc = parsed.dt.tz_localize("UTC") if parsed.dt.tz is None else parsed.dt.tz_convert("UTC")
        single, nonexistent = false, false
    elif basis == "offset_aware":
        utc, single, nonexistent = parsed.dt.tz_convert("UTC"), false, false
    else:
        raise ValueError(f"Unknown timestamp_basis: {basis!r}")
    return pd.DataFrame({"instant_utc": utc, "flag_dst_ambiguous_single": single,
                         "flag_nonexistent_time": nonexistent}, index=labels.index)


def to_interval_start_utc(labels: pd.Series, tz: str, basis: str, convention: str,
                          interval_minutes: int) -> pd.DataFrame:
    """Like ``label_instants_utc`` but returns ``interval_start_utc``.

    Interval-ending labels are shifted back by one interval *after* conversion to UTC, which
    is the only order that stays correct across both DST transitions.
    """
    out = label_instants_utc(labels, tz, basis)
    if convention == "ending":
        start = out["instant_utc"] - pd.Timedelta(minutes=interval_minutes)
    elif convention == "beginning":
        start = out["instant_utc"]
    else:
        raise ValueError(f"Unknown interval_convention: {convention!r}")
    return out.drop(columns="instant_utc").assign(interval_start_utc=start)


def expected_grid(start_utc: pd.Timestamp, end_utc: pd.Timestamp,
                  interval_minutes: int) -> pd.DatetimeIndex:
    """Every interval start between the first and last observed start (inclusive)."""
    return pd.date_range(start_utc, end_utc, freq=f"{interval_minutes}min", tz="UTC")


def local_start(interval_start_utc: pd.Series, tz: str) -> pd.Series:
    """Interval start in local wall-clock time (tz-aware)."""
    return interval_start_utc.dt.tz_convert(tz)


def expected_intervals_per_local_day(dates: pd.Series, tz: str,
                                     interval_minutes: int) -> pd.Series:
    """Expected interval count for each local calendar date (handles 23 / 25-hour days)."""
    unique = pd.to_datetime(pd.Series(pd.unique(dates.dropna())))
    midnight = unique.dt.tz_localize(tz, ambiguous=True, nonexistent="shift_forward")
    next_midnight = (unique + pd.Timedelta(days=1)).dt.tz_localize(
        tz, ambiguous=True, nonexistent="shift_forward")
    minutes = (next_midnight - midnight).dt.total_seconds() / 60.0
    lookup = dict(zip(unique.dt.date, (minutes // interval_minutes).astype(int)))
    return pd.to_datetime(dates).dt.date.map(lookup)


def dst_transition_dates(year: int, tz: str) -> list[pd.Timestamp]:
    """Local dates in ``year`` whose length is not 24 hours."""
    days = pd.Series(pd.date_range(f"{year}-01-01", f"{year}-12-31", freq="D").date)
    counts = expected_intervals_per_local_day(days, tz, 60)
    return [pd.Timestamp(d) for d, c in zip(days, counts) if c != 24]
