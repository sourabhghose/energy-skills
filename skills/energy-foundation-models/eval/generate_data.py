#!/usr/bin/env python3
"""Seed synthetic eval data for energy-foundation-models (planted truth, no real customers).

Writes to $SKILL_EVAL_DATA_DIR (default ./eval_data):
    feeder_load_30min.parquet      20 feeders, 30-min, UTC, with temp_c (efm-001)
    temp_forecast_30min.parquet    next-day temperature forecast per feeder (efm-001)
    lmp_hourly.parquet             3 nodes, hourly LMP in USD/MWh with negative hours (efm-002)
    substation_load_local.csv      hourly, NAIVE local time across both 2026 US DST transitions (efm-004)
    chips/chip_manifest.csv        HLS S30 chip manifest with S30 band codes (efm-005)

Usage:
    python3 generate_data.py                      # local
    SKILL_EVAL_DATA_DIR=/Volumes/<catalog>/energy_skills/eval/energy_foundation_models python3 generate_data.py
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261028
OUT = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "eval_data"))


def _temperature(idx: pd.DatetimeIndex, rng: np.random.Generator) -> np.ndarray:
    hour = idx.hour + idx.minute / 60
    return 8 + 6 * np.sin(2 * np.pi * (hour - 9) / 24) + rng.normal(0, 0.8, len(idx))


def feeder_load(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    idx = pd.date_range("2026-01-05", "2026-03-01 23:30", freq="30min", tz="UTC")
    future = pd.date_range(idx[-1] + pd.Timedelta("30min"), periods=48, freq="30min", tz="UTC")
    hist, fut = [], []
    for f in range(20):
        temp = _temperature(idx, rng)
        base = 3 + f * 0.2
        shape = 1.5 * np.sin(2 * np.pi * (idx.hour - 7) / 24) - 0.6 * (idx.dayofweek >= 5)
        load = base + shape + 0.08 * np.clip(15 - temp, 0, None) + rng.normal(0, 0.15, len(idx))
        hist.append(pd.DataFrame({"series_id": f"feeder_{f:03d}", "timestamp": idx,
                                  "load_mwh": load.round(4), "temp_c": temp.round(2)}))
        fut.append(pd.DataFrame({"series_id": f"feeder_{f:03d}", "timestamp": future,
                                 "temp_c_forecast": _temperature(future, rng).round(2)}))
    return pd.concat(hist, ignore_index=True), pd.concat(fut, ignore_index=True)


def lmp(rng: np.random.Generator) -> pd.DataFrame:
    idx = pd.date_range("2026-03-01", "2026-06-30 23:00", freq="1h", tz="UTC")
    frames = []
    for node in ("HUB_NORTH", "HUB_WEST", "NODE_SOLAR_01"):
        dist = np.minimum((idx.hour - 19) % 24, (19 - idx.hour) % 24)  # hours from ~noon Pacific
        solar_dip = -55 * np.exp(-dist ** 2 / 8) * (node == "NODE_SOLAR_01")
        price = 35 + 12 * np.sin(2 * np.pi * (idx.hour - 18) / 24) + solar_dip + rng.normal(0, 6, len(idx))
        frames.append(pd.DataFrame({"node": node, "interval_end_utc": idx, "lmp_usd_per_mwh": price.round(2)}))
    return pd.concat(frames, ignore_index=True)


def substation_local(rng: np.random.Generator) -> pd.DataFrame:
    """Naive local wall-clock export: 2026-03-08 02:00 missing, 2026-11-01 01:00 repeated."""
    utc = pd.date_range("2026-02-01", "2026-11-15", freq="1h", tz="UTC")
    local = utc.tz_convert("America/Chicago")
    load = 40 + 8 * np.sin(2 * np.pi * (local.hour - 8) / 24) - 3 * (local.dayofweek >= 5)
    load = load + rng.normal(0, 1.0, len(utc))
    return pd.DataFrame({"substation": "SUB_042",
                         "timestamp_local": local.tz_localize(None).strftime("%Y-%m-%d %H:%M:%S"),
                         "load_mw": load.round(3)})


def chip_manifest() -> pd.DataFrame:
    rows = []
    for i in range(12):
        rows.append({"chip_uri": f"/Volumes/<catalog>/energy_skills/eval/chips/corridor_{i:03d}.tif",
                     "bands": "B02,B03,B04,B8A,B11,B12", "height": 224, "width": 224,
                     "n_timesteps": 2, "units": "reflectance_x10000",
                     "acquired_dates": "2026-06-20,2026-09-15", "crs": "EPSG:32611",
                     "line_id": f"TL-{100 + i // 4}", "sensor": "HLS_S30"})
    return pd.DataFrame(rows)


def main() -> None:
    rng = np.random.default_rng(SEED)
    (OUT / "chips").mkdir(parents=True, exist_ok=True)
    hist, fut = feeder_load(rng)
    hist.to_parquet(OUT / "feeder_load_30min.parquet", index=False)
    fut.to_parquet(OUT / "temp_forecast_30min.parquet", index=False)
    lmp(rng).to_parquet(OUT / "lmp_hourly.parquet", index=False)
    substation_local(rng).to_csv(OUT / "substation_load_local.csv", index=False)
    chip_manifest().to_csv(OUT / "chips" / "chip_manifest.csv", index=False)
    print(f"wrote eval data to {OUT.resolve()}")


if __name__ == "__main__":
    main()
