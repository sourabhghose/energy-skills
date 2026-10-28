"""Time normalization, holiday calendars, degree days, and leakage-safe features.

Pure pandas / numpy. All features for a target hour use only (a) calendar facts, (b) weather
at that hour, and (c) load lags of at least ``horizon_hours`` — never anything later.

    from lf_features import to_hour_start_utc, holidays, build_features
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd


def to_hour_start_utc(ts: pd.Series, basis: str, convention: str, tz: str) -> pd.Series:
    """Convert load timestamps to hour-beginning UTC (fall-back hour resolved by order)."""
    parsed = pd.to_datetime(ts)
    if basis == "utc":
        utc = parsed.dt.tz_localize("UTC") if parsed.dt.tz is None else parsed.dt.tz_convert("UTC")
    elif basis == "local_naive":
        n = len(parsed)
        dst = parsed.dt.tz_localize(tz, ambiguous=np.ones(n, bool), nonexistent="NaT")
        std = parsed.dt.tz_localize(tz, ambiguous=np.zeros(n, bool), nonexistent="NaT")
        amb = dst.notna() & std.notna() & (dst != std)
        first = pd.Series(True, index=parsed.index)
        first[amb] = (parsed[amb].groupby(parsed[amb]).cumcount() == 0).to_numpy(dtype=bool)
        utc = parsed.dt.tz_localize(tz, ambiguous=first.to_numpy(),
                                    nonexistent="NaT").dt.tz_convert("UTC")
    else:
        raise ValueError(f"Unknown basis {basis!r}")
    return utc - pd.Timedelta(hours=1) if convention == "ending" else utc


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _nerc_year(y: int) -> list[date]:
    """NERC off-peak holidays; a Sunday holiday is observed Monday, Saturday is not moved."""
    fixed = [date(y, 1, 1), date(y, 7, 4), date(y, 12, 25)]
    moved = [d + timedelta(days=1) if d.weekday() == 6 else d for d in fixed]
    return moved + [_last_weekday(y, 5, 0), _nth_weekday(y, 9, 0, 1), _nth_weekday(y, 11, 3, 4)]


def _federal_year(y: int) -> list[date]:
    """US federal holidays with Saturday → Friday and Sunday → Monday observance."""
    fixed = [date(y, 1, 1), date(y, 7, 4), date(y, 11, 11), date(y, 12, 25)]
    if y >= 2021:
        fixed.append(date(y, 6, 19))
    observed = [d - timedelta(days=1) if d.weekday() == 5 else
                d + timedelta(days=1) if d.weekday() == 6 else d for d in fixed]
    floating = [_nth_weekday(y, 1, 0, 3), _nth_weekday(y, 2, 0, 3), _last_weekday(y, 5, 0),
                _nth_weekday(y, 9, 0, 1), _nth_weekday(y, 10, 0, 2), _nth_weekday(y, 11, 3, 4)]
    return observed + floating


def holidays(calendar: str, years: range) -> set[date]:
    """Holiday dates for ``calendar`` in ``nerc`` | ``us_federal`` | ``none``."""
    if calendar == "none":
        return set()
    builder = {"nerc": _nerc_year, "us_federal": _federal_year}.get(calendar)
    if builder is None:
        raise ValueError(f"Unknown holiday calendar {calendar!r}")
    return {d for y in years for d in builder(y)}


def degree_values(temp: pd.Series, hdd_base: float, cdd_base: float) -> pd.DataFrame:
    """Heating / cooling degrees (hourly → degree-hours, daily mean → degree-days)."""
    return pd.DataFrame({"hd": (hdd_base - temp).clip(lower=0),
                         "cd": (temp - cdd_base).clip(lower=0)}, index=temp.index)


def calendar_features(hour_start_utc: pd.Series, tz: str, holiday_dates: set[date]) -> pd.DataFrame:
    local = hour_start_utc.dt.tz_convert(tz)
    d = local.dt.date
    is_hol = d.isin(holiday_dates)
    return pd.DataFrame({
        "hour": local.dt.hour, "dow": local.dt.dayofweek, "month": local.dt.month,
        "is_holiday": is_hol.astype(int),
        "is_weekend_or_holiday": ((local.dt.dayofweek >= 5) | is_hol).astype(int),
        "local_date": d}, index=hour_start_utc.index)


def lag_hours(horizon_hours: int) -> list[int]:
    """Load lags allowed for a horizon: the smallest daily/weekly multiples ≥ horizon."""
    day = int(np.ceil(horizon_hours / 24) * 24)
    week = int(np.ceil(horizon_hours / 168) * 168)
    return sorted({day, week, week + 168})


def build_features(frame: pd.DataFrame, cfg, holiday_dates: set[date]) -> pd.DataFrame:
    """Feature matrix on an hourly UTC grid. ``frame``: hour_start_utc, load_mw, temp."""
    base = frame.sort_values("hour_start_utc").reset_index(drop=True)
    cal = calendar_features(base["hour_start_utc"], cfg.local_timezone, holiday_dates)
    deg = degree_values(base["temp"], cfg.hdd_base, cfg.cdd_base)
    lags = {f"load_lag_{h}": base["load_mw"].shift(h) for h in lag_hours(cfg.horizon_hours)}
    for name, h in ((n, int(n.rsplit("_", 1)[1])) for n in lags):
        if h < cfg.horizon_hours:
            raise AssertionError(f"{name} would leak: lag {h} < horizon {cfg.horizon_hours}")
    return pd.concat([base, cal, deg, pd.DataFrame(lags)], axis=1)


FEATURE_COLUMNS_BASE = ["hour", "dow", "month", "is_holiday", "is_weekend_or_holiday",
                        "temp", "hd", "cd"]


def feature_columns(cfg) -> list[str]:
    return FEATURE_COLUMNS_BASE + [f"load_lag_{h}" for h in lag_hours(cfg.horizon_hours)]
