"""Seeded synthetic production + GADS data with planted truth for energy-semantic-builder.

Truth is computed directly with pandas (independent of the skill's SQL). Task data ->
$SKILL_EVAL_DATA_DIR (default /tmp/semantic-eval); answer key -> $SKILL_EVAL_KEY_DIR
(default <data_dir>_answer_key).

Planted traps
    * gas is reported in cubic metres (gas_m3), not Mcf
    * a few high-rate, low-water wells and many low-rate, high-water wells: the average of
      per-well water cuts is far from the field water cut
    * wells shut in for part of the month: per-well averages differ from field boe/d
    * GADS fleet mixes 50 MW peakers and 800 MW base-load units: weighted != unweighted EAF
    * 2024 is a leap year and period hours follow DST (743 h in March, 745 h in November)

    python3 eval/generate_data.py
"""

from __future__ import annotations

import calendar
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 777
M3_PER_MCF = 28.316846592
TZ = "America/Chicago"


def production(rng) -> pd.DataFrame:
    days = pd.date_range("2025-03-01", "2025-03-31", freq="D")
    rows = []
    for w in range(40):
        big = w < 5
        oil = rng.uniform(800, 1500) if big else rng.uniform(15, 60)
        wc = rng.uniform(0.05, 0.2) if big else rng.uniform(0.7, 0.95)
        gor_scf = rng.uniform(800, 2500)
        shut = set(rng.choice(len(days), int(rng.integers(0, 12)), replace=False))
        for i, d in enumerate(days):
            on = i not in shut
            o = oil * rng.uniform(0.9, 1.1) if on else 0.0
            rows.append({"uwi": f"42-000-{w:05d}", "prod_date": d.date(), "field": "EAGLE",
                         "oil_bbl": o, "gas_m3": o * gor_scf / 1000 * M3_PER_MCF,
                         "wtr_bbl": o * wc / (1 - wc), "hours_on": 24.0 if on else 0.0})
    return pd.DataFrame(rows)


def gads(rng) -> pd.DataFrame:
    rows = []
    units = [(f"PKR{i}", 50.0) for i in range(6)] + [(f"BL{i}", 800.0) for i in range(2)]
    for unit, nmc in units:
        for month in range(1, 13):
            ph = _period_hours(2024, month)
            avail = ph * (rng.uniform(0.55, 0.8) if nmc < 100 else rng.uniform(0.9, 0.97))
            net = avail * nmc * (0.08 if nmc < 100 else 0.85) * rng.uniform(0.9, 1.1)
            rows.append({"unit_code": unit, "yr": 2024, "mo": month, "ph": ph, "nmc": nmc,
                         "ah": avail, "sh": avail * (0.15 if nmc < 100 else 0.95),
                         "foh": (ph - avail) * 0.4, "eudh": rng.uniform(0, 20),
                         "epdh": rng.uniform(0, 10), "esedh": 0.0, "efdh": rng.uniform(0, 15),
                         "efdhrs": 0.0, "net_gen": net})
    return pd.DataFrame(rows)


def _period_hours(year: int, month: int) -> float:
    start = pd.Timestamp(year, month, 1, tz=TZ)
    end = pd.Timestamp(year + (month == 12), month % 12 + 1, 1, tz=TZ)
    return (end - start).total_seconds() / 3600.0


def truth_upstream(df: pd.DataFrame) -> dict:
    gas_mcf = df["gas_m3"] / M3_PER_MCF
    days = df["prod_date"].nunique()
    boe = {name: float((df["oil_bbl"] + gas_mcf / r).sum() / days)
           for name, r in (("energy_6", 6.0), ("energy_5_8", 5.8))}
    per_well = df.groupby("uwi").agg(o=("oil_bbl", "sum"), w=("wtr_bbl", "sum"))
    return {"boe_per_day": boe,
            "boe_per_day_gas_unconverted_6": float((df["oil_bbl"] + df["gas_m3"] / 6).sum() / days),
            "water_cut_pct": float(100 * df["wtr_bbl"].sum() / (df["oil_bbl"].sum() + df["wtr_bbl"].sum())),
            "mean_of_well_water_cuts_pct": float((100 * per_well["w"] / (per_well["o"] + per_well["w"])).mean())}


def truth_generation(df: pd.DataFrame) -> dict:
    def eaf(w):
        num = ((df["ah"] - df["eudh"] - df["epdh"] - df["esedh"]) * w).sum()
        return float(100 * num / (df["ph"] * w).sum())
    cf = 100 * df["net_gen"].sum() / (df["nmc"] * df["ph"]).sum()
    cf_8760 = 100 * df["net_gen"].sum() / (df.groupby("unit_code")["nmc"].first().sum() * 8760)
    return {"eaf_pct": {"unweighted": eaf(1.0), "mw_weighted": eaf(df["nmc"])},
            "capacity_factor_pct": float(cf), "capacity_factor_pct_8760_wrong": float(cf_8760),
            "period_hours_2024": float(df.groupby("mo")["ph"].first().sum())}


def main() -> int:
    data_dir = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "/tmp/semantic-eval"))
    key_dir = Path(os.environ.get("SKILL_EVAL_KEY_DIR", f"{data_dir}_answer_key"))
    rng = np.random.default_rng(SEED)
    prod, units = production(rng), gads(rng)
    for task, frames in {"task_001": {"daily_volumes": prod}, "task_002": {"daily_volumes": prod},
                         "task_003": {"gads_monthly": units}, "task_004": {"gads_monthly": units},
                         "task_005": {"daily_volumes": prod, "gads_monthly": units}}.items():
        (data_dir / task).mkdir(parents=True, exist_ok=True)
        for name, df in frames.items():
            df.to_csv(data_dir / task / f"{name}.csv", index=False)
    key_dir.mkdir(parents=True, exist_ok=True)
    truth = {**truth_upstream(prod), **truth_generation(units)}
    (key_dir / "truth.json").write_text(json.dumps(truth, indent=2))
    print(f"wrote task data to {data_dir} and answer key to {key_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
