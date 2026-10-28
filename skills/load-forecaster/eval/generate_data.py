"""Generate seeded synthetic load-forecasting eval datasets with planted truth.

Task data (agent-visible CSVs) goes to ``--out-dir/<task_id>/``; the answer key goes to
``--truth-dir/truth.json`` and must never be uploaded next to the task data.

    python eval/generate_data.py --out-dir /tmp/lf-eval/tasks --truth-dir /tmp/lf-eval/truth
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

TZ = "America/Chicago"
HEAT_F, COOL_F, HEAT_SLOPE, COOL_SLOPE, BASE = 60.0, 70.0, 12.0, 30.0, 1000.0
NOISE = 0.02


def _temps(hours: pd.DatetimeIndex, rng: np.random.Generator, warm: float = 0.0) -> np.ndarray:
    doy, lh = hours.dayofyear.to_numpy(), hours.tz_convert(TZ).hour.to_numpy()
    walk = np.cumsum(rng.normal(0, 0.6, len(hours)))
    walk = walk - pd.Series(walk).rolling(240, min_periods=1).mean().to_numpy()
    return 55 + warm - 25 * np.cos(2 * np.pi * (doy - 15) / 365.25) + 8 * np.sin(
        2 * np.pi * (lh - 9) / 24) + walk


def _load(hours: pd.DatetimeIndex, temp_f: np.ndarray, rng: np.random.Generator,
          holiday_dates: set) -> tuple[np.ndarray, pd.Series]:
    local = hours.tz_convert(TZ)
    day = pd.Series(local.date, index=hours)
    tday = pd.Series(temp_f, index=hours).groupby(day.to_numpy()).transform("mean").to_numpy()
    lh = local.hour.to_numpy()
    shape = 0.8 + 0.25 * np.exp(-((lh - 18) ** 2) / 10) + 0.1 * np.exp(-((lh - 8) ** 2) / 4)
    off = (local.dayofweek.to_numpy() >= 5) | day.isin(holiday_dates).to_numpy()
    mult = np.where(off, 0.88, 1.0)
    daily = BASE + HEAT_SLOPE * np.clip(HEAT_F - tday, 0, None) + COOL_SLOPE * np.clip(tday - COOL_F, 0, None)
    clean = shape * mult * daily
    return clean * (1 + NOISE * rng.standard_normal(len(hours))), pd.Series(shape * mult, index=hours)


def _nerc(years) -> set:
    import datetime as dt
    out = set()
    for y in years:
        nov = [dt.date(y, 11, d) for d in range(1, 31) if dt.date(y, 11, d).weekday() == 3]
        may = [dt.date(y, 5, d) for d in range(1, 32) if dt.date(y, 5, d).weekday() == 0]
        sep = [dt.date(y, 9, d) for d in range(1, 31) if dt.date(y, 9, d).weekday() == 0]
        fixed = [dt.date(y, 1, 1), dt.date(y, 7, 4), dt.date(y, 12, 25)]
        out |= {d + dt.timedelta(days=1) if d.weekday() == 6 else d for d in fixed}
        out |= {nov[3], may[-1], sep[0]}
    return out


def _hours(start: str, end: str) -> pd.DatetimeIndex:
    return pd.date_range(start, end, freq="h", tz="UTC", inclusive="left")


def task_001(rng, out: Path) -> dict:
    """Day-ahead backtest: the noise floor makes any WAPE below ~1.2 % evidence of leakage."""
    hours = _hours("2021-01-01", "2024-01-02")
    temp = _temps(hours, rng)
    mw, _ = _load(hours[:-24], temp[:-24], rng, _nerc(range(2020, 2025)))
    pd.DataFrame({"ts_utc": (hours[:-24] + pd.Timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "load_mw": np.round(mw, 2)}).to_csv(out / "system_load.csv", index=False)
    pd.DataFrame({"station_id": "KAAA", "ts_utc": hours.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "temp_f": np.round(temp, 1)}).to_csv(out / "weather.csv", index=False)
    return {"min_plausible_wape_pct": round(100 * NOISE * np.sqrt(2 / np.pi) * 0.75, 2),
            "load_timestamp_convention": "hour-ending UTC"}


def task_002(rng, out: Path) -> dict:
    """Station choice and Celsius data: best station KBBB; balance points in °C."""
    hours = _hours("2021-01-01", "2023-01-01")
    temp = _temps(hours, rng)
    mw, _ = _load(hours, temp, rng, _nerc(range(2020, 2024)))
    c = (temp - 32) * 5 / 9
    frames = [pd.DataFrame({"station_id": "KBBB", "ts": hours, "temp": c}),
              pd.DataFrame({"station_id": "KCCC", "ts": hours, "temp": c + rng.normal(0, 4, len(c))}),
              pd.DataFrame({"station_id": "KDDD", "ts": hours, "temp": c}).sample(frac=0.6, random_state=2)]
    wx = pd.concat(frames).sort_values(["station_id", "ts"])
    wx.assign(ts=wx["ts"].dt.strftime("%Y-%m-%dT%H:%M:%SZ"), temp=wx["temp"].round(2)).to_csv(
        out / "weather.csv", index=False)
    pd.DataFrame({"ts_utc": hours.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "load_mw": np.round(mw, 2)}).to_csv(out / "zone_load.csv", index=False)
    return {"best_station": "KBBB", "temperature_unit": "C",
            "hdd_base_c": round((HEAT_F - 32) * 5 / 9, 1), "cdd_base_c": round((COOL_F - 32) * 5 / 9, 1)}


def task_003(rng, out: Path) -> dict:
    """Weather normalization of 2023 with a 2013-2022 normal period (2023 runs hot)."""
    hours = _hours("2013-01-01", "2024-01-02")
    temp = _temps(hours, rng)
    hot = np.asarray(hours.tz_convert(TZ).year == 2023)  # local calendar year
    temp = np.where(hot, temp + 3.0, temp)
    hol = _nerc(range(2012, 2025))
    mw, shape = _load(hours, temp, rng, hol)
    load_2023 = hot
    pd.DataFrame({"ts_utc": (hours[load_2023] + pd.Timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "load_mw": np.round(mw[load_2023], 2)}).to_csv(out / "load_2023.csv", index=False)
    pd.DataFrame({"station_id": "KEEE", "ts_utc": hours.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "temp_f": np.round(temp, 1)}).to_csv(out / "weather_2013_2023.csv", index=False)
    return {"actual_mwh_2023": round(float(mw[load_2023].sum()), 0),
            "normalized_mwh_2023": round(_normalized_truth(hours, temp, shape, hot), 0),
            "normal_years": [2013, 2022]}


def _normalized_truth(hours, temp, shape, target) -> float:
    local = hours.tz_convert(TZ)
    day = local.strftime("%Y-%m-%d")
    tday = pd.Series(temp).groupby(day).mean()
    dd = pd.DataFrame({"hdd": np.clip(HEAT_F - tday, 0, None), "cdd": np.clip(tday - COOL_F, 0, None)})
    dd["year"] = pd.to_datetime(dd.index).year
    dd["mmdd"] = pd.to_datetime(dd.index).strftime("%m-%d")
    normals = dd[dd["year"].between(2013, 2022)].groupby("mmdd")[["hdd", "cdd"]].mean()
    shape_day = pd.Series(shape.to_numpy()).groupby(day).sum()
    days_2023 = [d for d in shape_day.index if d.startswith("2023")]
    n = normals.loc[[d[5:] for d in days_2023]].to_numpy()
    return float((shape_day[days_2023].to_numpy() * (BASE + HEAT_SLOPE * n[:, 0] + COOL_SLOPE * n[:, 1])).sum())


def task_004(rng, out: Path) -> dict:
    """Hour-ending local-time load (repeated fall-back hour) covering Thanksgiving 2023."""
    hours = _hours("2021-01-01", "2023-12-01 06:00")
    temp = _temps(hours, rng)
    hol = _nerc(range(2020, 2024))
    mw, _ = _load(hours, temp, rng, hol)
    labels = (hours + pd.Timedelta(hours=1)).tz_convert(TZ).strftime("%Y-%m-%d %H:%M:%S")
    pd.DataFrame({"hour_ending_local": labels, "load_kw": np.round(mw * 1000, 0)}).to_csv(
        out / "feeder_load.csv", index=False)
    pd.DataFrame({"station_id": "KFFF", "ts_utc": hours.strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "temp_f": np.round(temp, 1)}).to_csv(out / "weather.csv", index=False)
    nov = np.asarray((hours.tz_convert(TZ).year == 2023) & (hours.tz_convert(TZ).month == 11))
    return {"nov_2023_mwh": round(float(mw[nov].sum()), 0), "load_unit": "kW",
            "hours_on_2023_11_05": 25, "thanksgiving_2023": "2023-11-23"}


TASKS = {"lf-001": task_001, "lf-002": task_002, "lf-003": task_003, "lf-004": task_004}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True, help="task data (agent-visible)")
    parser.add_argument("--truth-dir", type=Path, required=True, help="answer key (hidden)")
    parser.add_argument("--seed", type=int, default=2024)
    args = parser.parse_args(argv)
    truth = {}
    for task_id, build in TASKS.items():
        folder = args.out_dir / task_id
        folder.mkdir(parents=True, exist_ok=True)
        truth[task_id] = build(np.random.default_rng([args.seed, int(task_id[-3:])]), folder)
    args.truth_dir.mkdir(parents=True, exist_ok=True)
    (args.truth_dir / "truth.json").write_text(json.dumps(truth, indent=2))
    print(f"Wrote {len(TASKS)} tasks to {args.out_dir} and truth to {args.truth_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
