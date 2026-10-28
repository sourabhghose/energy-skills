#!/usr/bin/env python3
"""Seeded synthetic ESP fleet: historian samples, tag map, and CMMS work orders with traps.

Purpose: data for the equipment-pdm benchmark. Planted truth (see --print-truth):
  * 8 ESPs, 120 days, irregular ~20-min samples (UTC)
  * 3 qualifying failures with 5-day degradation (rising current instability, temperature rise)
  * 1 preventive work order that is NOT a failure
  * planned restarts with start-up current spikes (transients, not faults)
  * a 12-hour historian outage on ESP-02 (no samples) and PI digital states in analog tags
  * motor temperature tags in degF on ESP-01..04 and degC on ESP-05..08
  * historian tags that are not in the tag map

Usage:
    python3 generate_data.py [--out DIR]    # writes historian.csv, tag_map.csv, work_orders.csv
    python3 generate_data.py --print-truth
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 11
START = pd.Timestamp("2026-01-01", tz="UTC")
DAYS = 120
ASSETS = [f"ESP-{i:02d}" for i in range(1, 9)]
FAILURES = {"ESP-03": (70, "ELF"), "ESP-06": (100, "BRD"), "ESP-08": (110, "OHE")}
PM_ORDER = ("ESP-05", 60, "PM")           # preventive maintenance, not a failure
RESTARTS = {"ESP-01": [30, 75], "ESP-04": [45], "ESP-07": [20, 90]}   # 3-hour planned stops
OUTAGE = ("ESP-02", 40, 12)               # asset, day, hours with no samples
MOTOR_TEMP_C = {a: 100.0 + 2.0 * i for i, a in enumerate(ASSETS)}   # true running temperature
DEGF_ASSETS = set(ASSETS[:4])


def _times(rng: np.random.Generator) -> pd.DatetimeIndex:
    steps = rng.uniform(15, 25, int(DAYS * 24 * 3.2)).cumsum()
    return START + pd.to_timedelta(steps[steps < DAYS * 1440], unit="min")


def _running(asset: str, ts: pd.DatetimeIndex) -> np.ndarray:
    run = np.ones(len(ts), dtype=bool)
    for day in RESTARTS.get(asset, []):
        t0 = START + pd.Timedelta(days=day)
        run &= ~((ts >= t0) & (ts < t0 + pd.Timedelta(hours=3)))
    if asset in FAILURES:
        t0 = START + pd.Timedelta(days=FAILURES[asset][0])
        run &= ~((ts >= t0) & (ts < t0 + pd.Timedelta(days=4)))
    return run


def _signals(asset: str, ts: pd.DatetimeIndex, run: np.ndarray, rng: np.random.Generator) -> dict:
    n = len(ts)
    ramp = np.zeros(n)
    if asset in FAILURES:
        hours = (START + pd.Timedelta(days=FAILURES[asset][0]) - ts).total_seconds() / 3600.0
        ramp = np.where(hours > 0, np.clip(1 - hours / 120.0, 0, 1), 0.0)
    since_start = _hours_since_start(ts, run)
    spike = np.where(run & (since_start < 0.5), 35.0, 0.0)   # start-up inrush / settling
    amps = np.where(run, 48 + rng.normal(0, 0.5, n) + ramp * rng.normal(0, 7, n) + spike, 0.0)
    temp_c = np.where(run, MOTOR_TEMP_C[asset] + rng.normal(0, 0.8, n) + 25 * ramp, 60.0)
    temp = temp_c * 9 / 5 + 32 if asset in DEGF_ASSETS else temp_c
    pip = np.where(run, 900 + rng.normal(0, 6, n) - 120 * ramp, 1300.0)
    return {"MTR_AMPS": amps, "MTR_TEMP": temp, "PIP": pip, "RUN": run}


def _hours_since_start(ts: pd.DatetimeIndex, run: np.ndarray) -> np.ndarray:
    out, last = np.full(len(ts), 1e9), None
    for i in range(len(ts)):
        if run[i] and (i == 0 or not run[i - 1]):
            last = ts[i]
        out[i] = (ts[i] - last).total_seconds() / 3600.0 if run[i] and last is not None else 1e9
    return out


def _asset_frame(asset: str, rng: np.random.Generator) -> pd.DataFrame:
    ts = _times(rng)
    if asset == OUTAGE[0]:
        t0 = START + pd.Timedelta(days=OUTAGE[1])
        ts = ts[~((ts >= t0) & (ts < t0 + pd.Timedelta(hours=OUTAGE[2])))]
    sig = _signals(asset, ts, _running(asset, ts), rng)
    parts = [pd.DataFrame({"tag": f"{asset}.{k}", "ts": ts,
                           "value": np.where(v, "RUN", "STOP") if k == "RUN" else np.round(v, 3).astype(str)})
             for k, v in sig.items()]
    bad_idx = rng.choice(len(ts), 6, replace=False)
    states = pd.DataFrame({"tag": f"{asset}.MTR_AMPS", "ts": ts[bad_idx],
                           "value": ["I/O Timeout", "Shutdown", "Bad Input"] * 2})
    spare = pd.DataFrame({"tag": f"{asset}.SPARE_AI3", "ts": ts[:50], "value": "0"})
    return pd.concat([*parts, states, spare], ignore_index=True)


def build(seed: int = SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    historian = pd.concat([_asset_frame(a, rng) for a in ASSETS], ignore_index=True)
    tag_map = pd.DataFrame([
        {"tag": f"{a}.{s}", "asset_id": a, "equipment_class": "esp", "measurement": m,
         "unit": ("degF" if a in DEGF_ASSETS else "degC") if s == "MTR_TEMP" else u}
        for a in ASSETS for s, m, u in (("MTR_AMPS", "motor_current", "A"), ("MTR_TEMP", "motor_temperature", None),
                                        ("PIP", "intake_pressure", "psi"), ("RUN", "run_status", "state"))])
    wo = [{"wo_id": f"WO-{i + 1:03d}", "asset_id": a, "failure_mode": mode, "wo_type": "corrective",
           "failure_start": (START + pd.Timedelta(days=d)).isoformat(),
           "restored": (START + pd.Timedelta(days=d + 4)).isoformat()} for i, (a, (d, mode)) in enumerate(FAILURES.items())]
    wo.append({"wo_id": "WO-900", "asset_id": PM_ORDER[0], "failure_mode": "OTH", "wo_type": "preventive",
               "failure_start": (START + pd.Timedelta(days=PM_ORDER[1])).isoformat(),
               "restored": (START + pd.Timedelta(days=PM_ORDER[1], hours=6)).isoformat()})
    hist = historian.assign(ts=historian["ts"].map(lambda t: t.isoformat()))
    return {"historian": hist, "tag_map": tag_map, "work_orders": pd.DataFrame(wo)}


def truth() -> dict:
    hottest = max(MOTOR_TEMP_C, key=MOTOR_TEMP_C.get)
    return {
        "failures": {a: {"day": d, "mode": m, "date": str((START + pd.Timedelta(days=d)).date())}
                     for a, (d, m) in FAILURES.items()},
        "not_a_failure": {"wo_id": "WO-900", "asset": PM_ORDER[0], "type": "preventive"},
        "hottest_motor_asset": hottest, "hottest_motor_temp_c": MOTOR_TEMP_C[hottest] + 0.0,
        "hottest_raw_number_asset": max(DEGF_ASSETS, key=lambda a: MOTOR_TEMP_C[a]),
        "degF_assets": sorted(DEGF_ASSETS),
        "outage": {"asset": OUTAGE[0], "start": str(START + pd.Timedelta(days=OUTAGE[1])), "hours": OUTAGE[2]},
        "digital_states_per_asset": 6, "unmapped_tag_suffix": "SPARE_AI3",
        "planned_restarts": RESTARTS,
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
    for name, df in build().items():
        df.to_csv(out / f"{name}.csv", index=False)
        print(f"wrote {len(df)} rows to {out / f'{name}.csv'}")


if __name__ == "__main__":
    main()
