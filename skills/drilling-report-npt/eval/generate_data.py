#!/usr/bin/env python3
"""Seeded synthetic DDR time logs with planted NPT, traps, and reconciliation faults.

Purpose: data for the drilling-report-npt benchmark. Planted truth:
  * 10 NPT events (coded, uncoded-in-text, and weather), across 6 wells on 2 rigs
  * 3 text traps: negated losses, offset-well losses, precautionary "possible sticking"
  * a 2-hour gap (W-102, 2026-11-03) and a 1-hour overlap (W-105, 2026-11-04)
  * a correct 25-hour log on the DST fall-back day (2026-11-01, America/Chicago)

Usage:
    python3 generate_data.py [--out DIR]       # DIR defaults to $SKILL_EVAL_DATA_DIR or ./eval_data
    python3 generate_data.py --print-truth     # planted truth used by expectations.json
Then load: CREATE TABLE energy_catalog.energy_skills_eval.ddr_time_log AS
           SELECT * FROM read_files('/Volumes/.../ddr_time_log.csv', format => 'csv', header => true)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

TZ = "America/Chicago"
DAYS = pd.date_range("2026-10-29", periods=7, freq="D")
RIGS = {"W-101": ("R7", "Acme Drilling"), "W-102": ("R7", "Acme Drilling"), "W-103": ("R7", "Acme Drilling"),
        "W-104": ("R9", "Borealis Rigs"), "W-105": ("R9", "Borealis Rigs"), "W-106": ("R9", "Borealis Rigs")}

# (well, day index, start hour into day, hours, code, remark, truth category or None, trap)
EVENTS = [
    ("W-101", 0, 6, 3, "8", "Repair mud pump #2 liner washout.", "EQUIPMENT_RIG", None),
    ("W-101", 1, 10, 4, "5", "Partial losses 60 bbl/hr at 9,850 ft, pumped 40 ppb LCM pill.", "LOST_CIRCULATION", None),
    ("W-102", 2, 0, 12, "2", "Drilled 9,900-10,300 ft. No losses observed.", None, "negated"),
    ("W-102", 3, 4, 6, "6", "Tripped out. Offset well W-099 experienced total losses at this depth; monitored trip tank.", None, "offset"),
    ("W-103", 1, 12, 6, "21", "Waiting on weather - lightning within 5 miles, rig floor evacuated.", "WAIT_WEATHER", None),
    ("W-103", 4, 2, 8, "19", "Fishing for parted drill pipe with overshot.", "FISHING", None),
    ("W-104", 0, 8, 5, "6", "Worked stuck pipe, jarred down 40 times, pipe free.", "STUCK_PIPE", None),
    ("W-104", 2, 14, 7, "21", "MWD tool failure, no pulse; POOH to change tool.", "EQUIPMENT_DOWNHOLE", None),
    ("W-105", 1, 6, 4, "2", "Short trip as precaution against possible differential sticking.", None, "hypothetical"),
    ("W-105", 3, 9, 5, "21", "Waiting on casing delivery from yard.", "WAIT_MATERIALS", None),
    ("W-106", 0, 3, 9, "5", "Took 15 bbl kick, shut in well, circulated out gas with driller's method.", "WELL_CONTROL", None),
    ("W-106", 5, 16, 2, "8", "Top drive repair - replaced IBOP actuator.", "EQUIPMENT_RIG", None),
]
GAP = ("W-102", 5, 2.0)        # last line of the day ends 2 h early
OVERLAP = ("W-105", 6, 1.0)    # second line starts 1 h before the first ends
PRODUCTIVE = ["Drilled ahead {a:,}-{b:,} ft, ROP steady.", "Drilled {a:,} to {b:,} ft with RSS, survey every stand."]


def _day_bounds(day: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = day.tz_localize(TZ)
    return start, (day + pd.Timedelta(days=1)).tz_localize(TZ)


def _segments(well: str, d: int) -> list[tuple[float, float, str, str]]:
    """(start_offset_h, hours, code, remark) covering the day, around any planted event."""
    start, end = _day_bounds(DAYS[d])
    total = (end - start).total_seconds() / 3600.0
    ev = [e for e in EVENTS if e[0] == well and e[1] == d]
    if not ev:
        return [(0.0, total / 2, "2", ""), (total / 2, total / 2, "2", "")]
    _, _, s, h, code, remark, _, _ = ev[0]
    segs = [(0.0, float(s), "2", "")] if s > 0 else []
    segs.append((float(s), float(h), code, remark))
    if s + h < total:
        segs.append((float(s + h), total - s - h, "2", ""))
    return segs


def _rows_for_day(well: str, d: int, rng: np.random.Generator, counter: list[int]) -> list[dict]:
    start, _ = _day_bounds(DAYS[d])
    rig, contractor = RIGS[well]
    rows = []
    for off, hours, code, remark in _segments(well, d):
        depth = int(8000 + 300 * d + rng.integers(0, 200))
        footage = int(hours * rng.uniform(35, 60)) if not remark else None
        text = remark or PRODUCTIVE[int(rng.integers(0, 2))].format(a=depth, b=depth + (footage or 0))
        counter[0] += 1
        rows.append({"row_id": f"L{counter[0]:05d}", "well_id": well, "rig_id": rig, "contractor": contractor,
                     "start_time": start + pd.Timedelta(hours=off),
                     "end_time": start + pd.Timedelta(hours=off + hours),
                     "activity_code": code, "remarks": text, "footage_ft": footage})
    return rows


def _apply_faults(df: pd.DataFrame) -> pd.DataFrame:
    day = df["start_time"].dt.tz_convert(TZ).dt.tz_localize(None).dt.normalize()
    gw, gd, gh = GAP
    gap_idx = df[(df["well_id"] == gw) & (day == DAYS[gd])].index[-1]
    ow, od, oh = OVERLAP
    ov_idx = df[(df["well_id"] == ow) & (day == DAYS[od])].index[1]
    end = df["end_time"].copy()
    end.loc[gap_idx] = end.loc[gap_idx] - pd.Timedelta(hours=gh)
    start = df["start_time"].copy()
    start.loc[ov_idx] = start.loc[ov_idx] - pd.Timedelta(hours=oh)
    return df.assign(start_time=start, end_time=end)


def build(seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    counter = [0]
    rows = [r for well in RIGS for d in range(len(DAYS)) for r in _rows_for_day(well, d, rng, counter)]
    return _apply_faults(pd.DataFrame(rows))


def truth() -> dict:
    """Planted answers under: union, weather separate, 00:00 reporting day."""
    by_rig: dict = {}
    weather: dict = {}
    for well, _, _, hours, _, _, cat, _ in EVENTS:
        rig = RIGS[well][0]
        if cat == "WAIT_WEATHER":
            weather[rig] = weather.get(rig, 0) + hours
        elif cat:
            by_rig.setdefault(rig, {}).setdefault(cat, 0)
            by_rig[rig][cat] += hours
    return {
        "npt_hours_by_rig_category": by_rig,
        "npt_hours_by_rig_total": {r: sum(v.values()) for r, v in by_rig.items()},
        "weather_downtime_by_rig": weather,
        "lost_circulation_wells": sorted({e[0] for e in EVENTS if e[6] == "LOST_CIRCULATION"}),
        "trap_wells": {e[7]: e[0] for e in EVENTS if e[7]},
        "recon_failures": [{"well_id": GAP[0], "report_day": str(DAYS[GAP[1]].date()), "status": "short_day"},
                           {"well_id": OVERLAP[0], "report_day": str(DAYS[OVERLAP[1]].date()), "status": "overlap"}],
        "dst_day_ok": "2026-11-01",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=os.environ.get("SKILL_EVAL_DATA_DIR", "eval_data"))
    parser.add_argument("--print-truth", action="store_true")
    args = parser.parse_args()
    if args.print_truth:
        print(json.dumps(truth(), indent=2))
        return
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    df = build()
    iso = df.assign(start_time=df["start_time"].map(lambda t: t.isoformat()),
                    end_time=df["end_time"].map(lambda t: t.isoformat()))
    iso.to_csv(out / "ddr_time_log.csv", index=False)
    print(f"wrote {len(df)} time-log lines to {out / 'ddr_time_log.csv'}")


if __name__ == "__main__":
    main()
