"""ISO/RTO market data core: conventions registry, timestamp normalization (hour-ending, DST
repeated hour, interval beginning vs ending), interval-grid checks, NERC holidays, peak masks,
and node grounding.

Pure pandas/numpy. All normalized data carries `interval_start_utc`, `interval_end_utc`
and `interval_minutes`.
"""

from __future__ import annotations

import difflib
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

CONVENTIONS_FILE = Path(__file__).resolve().parent.parent / "assets" / "iso_conventions.json"
TIMESTAMP_CONVENTIONS = ("interval_beginning", "interval_ending")
PEAK_DEFINITIONS = ("5x16", "2x16", "7x8", "wrap", "7x24")


class DecisionRequired(ValueError):
    """A decision point that belongs to the user was not supplied."""

    def __init__(self, name: str, options, why: str = ""):
        self.name, self.options = name, list(options)
        super().__init__(f"Decision required: {name!r}; choose one of {self.options}. {why}".strip())


def require(name: str, value, options, why: str = ""):
    if value is None or value not in options:
        raise DecisionRequired(name, options, why)
    return value


def load_conventions(path: Path = CONVENTIONS_FILE) -> dict:
    data = json.loads(path.read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def iso_convention(iso: str) -> dict:
    conv = load_conventions()
    if iso not in conv:
        raise DecisionRequired("iso", sorted(conv))
    return conv[iso]


# ----------------------------------------------------------------------------- timestamps

def from_utc(df: pd.DataFrame, ts_col: str, convention: str, interval_minutes: int) -> pd.DataFrame:
    """Normalize a UTC (or offset-aware) timestamp column that marks interval start or end."""
    require("source_timestamp_convention", convention, TIMESTAMP_CONVENTIONS)
    ts = pd.to_datetime(df[ts_col], utc=True)
    step = pd.Timedelta(minutes=interval_minutes)
    start = ts if convention == "interval_beginning" else ts - step
    return df.assign(interval_start_utc=start, interval_end_utc=start + step, interval_minutes=interval_minutes)


def _localize_hour_starts(naive: pd.Series, tz: str, repeated: pd.Series) -> pd.Series:
    """Localize local-prevailing hour starts. `repeated` marks the second (standard-time) fall-back hour."""
    idx = pd.DatetimeIndex(naive)
    nonexistent = idx.tz_localize(tz, ambiguous=True, nonexistent="NaT").isna()
    ambiguous_mask = idx.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward").isna()
    if nonexistent.any():
        bad = sorted({str(t) for t in idx[nonexistent]})[:5]
        raise ValueError(f"Hour labels that do not exist in {tz} (spring-forward gap): {bad}")
    flags = np.where(ambiguous_mask, ~repeated.to_numpy(dtype=bool), True)  # True = DST (first occurrence)
    return pd.Series(idx.tz_localize(tz, ambiguous=flags), index=naive.index)


def from_hour_ending(df: pd.DataFrame, tz: str, date_col: str = "date", he_col: str = "hour_ending",
                     repeated_col: str | None = None, interval_col: str | None = None,
                     interval_minutes: int = 60) -> pd.DataFrame:
    """Normalize date + hour-ending (1-24, or 'HH:00'/'02X') [+ sub-hourly interval number] to UTC.

    The repeated fall-back hour must be identified by `repeated_col` (ERCOT DSTFlag='Y') or an 'X'
    suffix on the hour label (ISO-NE '02X'); otherwise duplicates are rejected.
    """
    he_raw = df[he_col].astype(str).str.strip()
    x_suffix = he_raw.str.upper().str.endswith("X")
    he = he_raw.str.upper().str.rstrip("X").str.split(":").str[0].astype(int)
    if not he.between(1, 24).all():
        raise ValueError("hour_ending must be 1-24 (repeated hour flagged separately, not as 25)")
    repeated = x_suffix
    if repeated_col is not None:
        repeated = repeated | df[repeated_col].astype(str).str.upper().isin({"Y", "TRUE", "1"})
    hour_start = pd.to_datetime(df[date_col]) + pd.to_timedelta(he - 1, unit="h")
    start_local = _localize_hour_starts(hour_start, tz, repeated)
    if interval_col is not None:
        start_local = start_local + pd.to_timedelta((df[interval_col].astype(int) - 1) * interval_minutes, unit="m")
    start = start_local.dt.tz_convert("UTC")
    step = pd.Timedelta(minutes=interval_minutes)
    out = df.assign(interval_start_utc=start, interval_end_utc=start + step, interval_minutes=interval_minutes)
    dupes = out.duplicated(subset=["node", "interval_start_utc"]) if "node" in out else out.duplicated(
        subset=["interval_start_utc"])
    if dupes.any():
        raise ValueError(f"{int(dupes.sum())} duplicate intervals after normalization: the repeated DST hour "
                         "is not flagged (pass repeated_col, e.g. ERCOT DSTFlag)")
    return out


def convention_evidence(ts_local: pd.Series, interval_minutes: int) -> str:
    """Hint from the data: do daily labels start at 00:00 (beginning) or at the first interval end?"""
    minutes = ts_local.dt.hour * 60 + ts_local.dt.minute
    first = int(minutes.min())
    if first == 0 and (minutes == 24 * 60 - interval_minutes).any():
        return "labels run 00:00 to 23:{:02d}: consistent with interval_beginning".format(60 - interval_minutes)
    if first == interval_minutes % (24 * 60):
        return f"labels start at {first // 60:02d}:{first % 60:02d}: consistent with interval_ending"
    return "inconclusive: check the report specification"


# ----------------------------------------------------------------------------- grid checks

def interval_grid_report(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    """Per node and local day: rows present vs expected (23/24/25-hour days handled)."""
    local = df["interval_start_utc"].dt.tz_convert(tz)
    day = local.dt.date
    frame = df.assign(_day=day)
    minutes = int(df["interval_minutes"].iloc[0])
    counts = frame.groupby(["node", "_day"]).size().rename("rows").reset_index()

    def expected(d: date) -> int:
        start = pd.Timestamp(d).tz_localize(tz)
        end = pd.Timestamp(d + timedelta(days=1)).tz_localize(tz)
        return int((end - start) / pd.Timedelta(minutes=minutes))

    counts["expected"] = counts["_day"].map(expected)
    counts["day_hours"] = counts["expected"] * minutes / 60
    return counts.rename(columns={"_day": "local_date"}).assign(complete=lambda x: x["rows"] == x["expected"])


# ----------------------------------------------------------------------------- holidays and peaks

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def nerc_holidays(year: int) -> set[date]:
    """NERC off-peak holidays. Sunday holidays move to Monday; Saturday holidays do not move."""
    fixed = [date(year, 1, 1), date(year, 7, 4), date(year, 12, 25)]
    moved = [d + timedelta(days=1) if d.weekday() == 6 else d for d in fixed]
    return set(moved) | {_last_weekday(year, 5, 0), _nth_weekday(year, 9, 0, 1), _nth_weekday(year, 11, 3, 4)}


def peak_mask(interval_start_utc: pd.Series, definition: str, peak_tz: str) -> pd.Series:
    """True where the interval falls in the peak block, evaluated in `peak_tz` local prevailing time.

    5x16 = Mon-Fri excl. NERC holidays, HE7-HE22 (06:00-22:00 local). 2x16 = weekends + NERC
    holidays HE7-HE22. 7x8 = every day HE1-HE6 and HE23-HE24. wrap = 2x16 + 7x8. 7x24 = all.
    """
    require("peak_definition", definition, PEAK_DEFINITIONS)
    local = interval_start_utc.dt.tz_convert(peak_tz)
    years = range(local.dt.year.min(), local.dt.year.max() + 1)
    holidays = set().union(*(nerc_holidays(y) for y in years))
    is_hol = local.dt.date.isin(holidays)
    weekday = (local.dt.weekday < 5) & ~is_hol
    day_block = local.dt.hour.between(6, 21)
    masks = {"5x16": weekday & day_block, "2x16": ~weekday & day_block, "7x8": ~day_block}
    masks["wrap"] = masks["2x16"] | masks["7x8"]
    masks["7x24"] = pd.Series(True, index=local.index)
    return masks[definition]


# ----------------------------------------------------------------------------- node grounding

def ground_nodes(requested: list[str], available: list[str]) -> dict:
    """Split requested node names into found / missing; suggest close matches but never substitute."""
    avail = set(available)
    found = [n for n in requested if n in avail]
    missing = {n: difflib.get_close_matches(n, sorted(avail), n=3, cutoff=0.6) for n in requested if n not in avail}
    return {"found": found, "missing": missing}
