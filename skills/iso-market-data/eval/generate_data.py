"""Seeded synthetic ISO price data with planted truth for the iso-market-data benchmark.

Truth is computed with independent arithmetic (zoneinfo + loops), not the skill's code.

    SKILL_EVAL_DATA_DIR=/tmp/energy-skills-eval/iso python eval/generate_data.py --check
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

SEED = 825
OUT = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "/tmp/energy-skills-eval/iso"))
HERE = Path(__file__).resolve().parent
NOV_2025_HOLIDAYS = {date(2025, 11, 27)}


def task_001(rng) -> tuple[pd.DataFrame, dict]:
    """ERCOT RT SPP, November 2025 (25-hour Nov 2), hour-ending labels with DSTFlag."""
    tz = ZoneInfo("America/Chicago")
    rows, peak, off = [], [], []
    t = datetime(2025, 11, 1, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    end = datetime(2025, 12, 1, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    seen = set()
    while t < end:
        local = t.astimezone(tz)
        price = round(25 + 20 * np.sin(np.pi * local.hour / 24) + rng.normal(0, 3), 2)
        he = local.hour + 1
        key = (local.date(), he)
        flag = "Y" if key in seen else "N"
        seen.add(key)
        for i in range(1, 5):
            rows.append({"node": "HB_NORTH", "date": local.date().isoformat(), "hour_ending": f"{he:02d}:00",
                         "interval": i, "dst_flag": flag, "lmp": price})
        is_peak = local.weekday() < 5 and local.date() not in NOV_2025_HOLIDAYS and 6 <= local.hour <= 21
        (peak if is_peak else off).append(price)
        t += timedelta(hours=1)
    truth = {"hours_in_month": len(peak) + len(off), "onpeak_5x16_avg": round(float(np.mean(peak)), 3),
             "offpeak_avg": round(float(np.mean(off)), 3)}
    return pd.DataFrame(rows), truth


def task_002(rng) -> tuple[pd.DataFrame, dict]:
    """PJM 5-min RT, interval-beginning UTC, with missing intervals in one hour."""
    ts = pd.date_range("2025-07-15T04:00:00Z", periods=24 * 12, freq="5min")
    lmp = np.round(35 + 15 * np.sin(np.arange(len(ts)) / 40) + rng.normal(0, 4, len(ts)), 2)
    df = pd.DataFrame({"node": "MY_PNODE", "datetime_beginning_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "lmp": lmp})
    hour = pd.Timestamp("2025-07-15T20:00:00Z")
    drop = [i for i, t in enumerate(ts) if t >= hour and t < hour + pd.Timedelta(hours=1)][3:6]
    keep = [i for i in range(len(ts)) if i not in drop]
    in_hour = [lmp[i] for i in keep if hour <= ts[i] < hour + pd.Timedelta(hours=1)]
    truth = {"hour_2025_07_15T20Z_time_weighted": round(float(np.mean(in_hour)), 3),
             "hour_2025_07_15T20Z_covered_minutes": 5 * len(in_hour)}
    return df.iloc[keep].reset_index(drop=True), truth


def task_003(rng) -> tuple[pd.DataFrame, dict]:
    """NYISO zonal LBMP with published congestion (LBMP = energy + loss - congestion)."""
    ts = pd.date_range("2025-08-01T04:00:00Z", periods=24 * 7, freq="h")
    rows, impact = [], {}
    for zone, mean_published in (("N.Y.C.", -18.0), ("WEST", 4.0), ("CAPITL", -6.0)):
        energy = 40 + rng.normal(0, 3, len(ts))
        loss = rng.normal(1.5, 0.3, len(ts))
        cong = mean_published + rng.normal(0, 1, len(ts))
        rows.append(pd.DataFrame({"node": zone, "time_stamp_utc": ts, "energy": energy.round(2),
                                  "loss": loss.round(2), "congestion": cong.round(2)}))
        impact[zone] = float(-cong.round(2).mean())
    df = pd.concat(rows, ignore_index=True)
    df["lmp"] = (df["energy"] + df["loss"] - df["congestion"]).round(2)
    top = max(impact, key=impact.get)
    return df, {"zone_highest_congestion_price_impact": top,
                "nyc_mean_congestion_adder": round(impact["N.Y.C."], 2)}


def task_004(rng) -> tuple[pd.DataFrame, dict]:
    """CAISO 5-min RT battery: charge midday (negative prices), discharge evening ramp."""
    ts = pd.date_range("2025-09-10T07:00:00Z", periods=24 * 12, freq="5min")
    local_h = ts.tz_convert("America/Los_Angeles").hour
    frac = ts.minute.to_numpy() / 55.0  # position within the hour, 0..1
    evening = (local_h >= 18) & (local_h < 21)
    lmp = np.where((local_h >= 10) & (local_h < 14), -15.0, 40.0)
    lmp = np.where(evening, 60.0 + 180.0 * frac + rng.normal(0, 5, len(ts)), lmp).round(2)
    mwh = np.where((local_h >= 10) & (local_h < 14), -25 / 12, 0.0)
    mwh = np.where(evening, 2 * 30 / 12 * frac, mwh).round(4)
    df = pd.DataFrame({"node": "BESS_1_APND", "INTERVALSTARTTIME_GMT": ts.strftime("%Y-%m-%dT%H:%M:%S-00:00"),
                       "lmp": lmp, "mwh": mwh})
    hourly_naive = df.assign(h=ts.floor("h")).groupby("h").agg(p=("lmp", "mean"), e=("mwh", "sum"))
    return df, {"rt_revenue_usd": round(float((lmp * mwh).sum()), 2),
                "naive_hourly_revenue_usd": round(float((hourly_naive.p * hourly_naive.e).sum()), 2)}


TASKS = {"iso-001": task_001, "iso-002": task_002, "iso-003": task_003, "iso-004": task_004}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rng = np.random.default_rng(SEED)
    expectations = {t["task_id"]: t for t in json.loads((HERE / "expectations.json").read_text())} \
        if args.check else {}
    for task_id, make in TASKS.items():
        df, truth = make(rng)
        folder = OUT / task_id
        folder.mkdir(parents=True, exist_ok=True)
        df.to_csv(folder / "prices.csv", index=False)
        if args.check:
            checks = expectations[task_id]["deterministic_checks"]
            planted = {**checks["numeric_truth"], **checks.get("naive_trap", {})}
            for key, value in truth.items():
                assert planted[key] == value, f"{task_id}.{key}: {planted[key]} != {value}"
        print(f"{task_id}: {len(df)} rows -> {folder}  truth={json.dumps(truth)}")


if __name__ == "__main__":
    main()
