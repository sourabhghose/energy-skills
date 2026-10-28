"""Seeded synthetic wind SCADA and PV data with planted truth for the wind-solar-performance benchmark.

    SKILL_EVAL_DATA_DIR=/tmp/energy-skills-eval/wsp python eval/generate_data.py --check
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 61400
OUT = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "/tmp/energy-skills-eval/wsp"))
HERE = Path(__file__).resolve().parent
RATED = 2000.0


def _curve() -> pd.DataFrame:
    ws = np.arange(0, 25.5, 0.5)
    p = np.where(ws < 3, 0, np.where(ws >= 12, RATED, RATED * ((ws - 3) / 9) ** 3))
    return pd.DataFrame({"ws_ms": ws, "power_kw": p})


def _turbine(rng, ts, tid, perf):
    curve = _curve()
    ws = np.clip(rng.weibull(2.0, len(ts)) * 8.5, 0, 30).round(2)
    temp = 12 + rng.normal(0, 3, len(ts))
    rho = 1013.25 * 100 / (287.05 * (temp + 273.15))
    expected = np.interp(ws * (rho / 1.225) ** (1 / 3), curve.ws_ms, curve.power_kw)
    return pd.DataFrame({"turbine_id": tid, "timestamp": ts, "wind_speed_ms": ws, "power_kw": expected * perf,
                         "ambient_temp_c": temp.round(2), "pressure_hpa": 1013.25, "state": "running",
                         "setpoint_kw": RATED}), expected


def wind_tasks(rng) -> tuple[dict, dict]:
    ts = pd.date_range("2025-06-01", periods=30 * 144, freq="10min", tz="Europe/London")
    frames, truth, avail = [], {}, {}
    for i, perf in enumerate([1.0, 1.0, 0.93, 1.0, 1.0], 1):
        tid = f"WTG{i:02d}"
        df, expected = _turbine(rng, ts, tid, perf)
        if tid == "WTG01":  # 3 days curtailed to 800 kW by the TSO
            sl = slice(1440, 1440 + 432)
            df.loc[df.index[sl], ["state", "setpoint_kw"]] = ["curtailed", 800.0]
            df.loc[df.index[sl], "power_kw"] = np.minimum(expected[sl], 800.0)
            truth["wtg01_curtailment_mwh"] = round(float((expected[sl] - np.minimum(expected[sl], 800)).sum() / 6000), 3)
        if tid == "WTG04":  # 2 days fault + 1 day grid outage
            df.loc[df.index[288:576], ["state", "power_kw"]] = ["fault", 0.0]
            df.loc[df.index[2880:3024], ["state", "power_kw"]] = ["grid_outage", 0.0]
            avail = {"wtg04_time_avail_excl_external": round(1 - 2 / 29, 4),
                     "wtg04_time_avail_incl_external": round(1 - 3 / 30, 4)}
        frames.append(df)
    truth["underperforming_turbine"] = "WTG03"
    truth["wtg03_performance_gap_pct"] = 7.0
    scada = pd.concat(frames, ignore_index=True)
    return {"wsp-001": scada, "wsp-002": scada}, {"wsp-001": truth, "wsp-002": avail}


def _pv(rng, days, start, rd_pct, curtail_days=()):
    ts = pd.date_range(start, periods=days * 96, freq="15min", tz="America/Phoenix")
    hour = ts.hour + ts.minute / 60
    poa = np.clip(np.sin(np.pi * (hour - 6) / 12), 0, None) * 1000 * np.repeat(rng.uniform(0.7, 1.0, days), 96)
    t_amb = 22 + 10 * np.sin(2 * np.pi * (ts.dayofyear - 100) / 365)
    t_mod = poa * np.exp(-3.56 - 0.075 * 2.0) + t_amb
    t_cell = t_mod + poa / 1000 * 3
    years = (ts - ts[0]).days / 365.25
    ac = 2000 * poa / 1000 * (1 - 0.0037 * (t_cell - 25)) * 0.8 * (1 + rd_pct / 100) ** years
    df = pd.DataFrame({"timestamp": ts, "poa_wm2": poa.round(1), "ghi_wm2": (poa * 0.9).round(1),
                       "ac_power_kw": np.minimum(ac, 1700.0).round(2), "module_temp_c": t_mod.round(2),
                       "inverter_status": "ok", "setpoint_kw": 1700.0})
    for d in curtail_days:
        sel = ts.normalize() == ts.normalize()[d * 96]
        df.loc[sel, "setpoint_kw"] = 600.0
        df.loc[sel, "ac_power_kw"] = df.loc[sel, "ac_power_kw"].clip(upper=600.0)
    return df


def solar_tasks(rng) -> tuple[dict, dict]:
    ghi_only = _pv(rng, 31, "2025-07-01", 0.0).drop(columns=["poa_wm2"])
    long = _pv(rng, 3 * 365 + 30, "2022-01-01", -0.7, curtail_days=range(100, 1000, 45))
    return ({"wsp-003": ghi_only, "wsp-004": long},
            {"wsp-003": {"pr_computed_from_ghi": False}, "wsp-004": {"rd_pct_per_year": -0.7}})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rng = np.random.default_rng(SEED)
    data, truth = wind_tasks(rng)
    sdata, struth = solar_tasks(rng)
    data, truth = {**data, **sdata}, {**truth, **struth}
    exp_path = HERE / "expectations.json"
    expectations = {t["task_id"]: t for t in json.loads(exp_path.read_text())} if args.check else {}
    for task_id, df in data.items():
        folder = OUT / task_id
        folder.mkdir(parents=True, exist_ok=True)
        name = "scada_10min.csv" if task_id in ("wsp-001", "wsp-002") else "pv_15min.csv"
        df.to_csv(folder / name, index=False)
        if task_id in ("wsp-001", "wsp-002"):
            _curve().to_csv(folder / "warranted_curve.csv", index=False)
        if args.check:
            planted = expectations[task_id]["deterministic_checks"]["numeric_truth"]
            for key, value in truth[task_id].items():
                assert planted[key] == value, f"{task_id}.{key}: {planted[key]} != {value}"
        print(f"{task_id}: {len(df)} rows -> {folder}")
    print(json.dumps(truth, indent=1))


if __name__ == "__main__":
    main()
