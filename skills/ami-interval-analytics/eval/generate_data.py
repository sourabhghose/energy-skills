"""Generate seeded synthetic AMI eval datasets with planted truth.

Writes one folder per task under ``--out-dir`` (CSV files the agent may see) and a single
``truth.json`` under ``--truth-dir`` (the answer key; never upload it next to the task data).

    python eval/generate_data.py --out-dir /tmp/ami-eval/tasks --truth-dir /tmp/ami-eval/truth
    databricks fs cp -r /tmp/ami-eval/tasks dbfs:/Volumes/energy_catalog/energy_skills/eval/ami
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

TZ = "America/Chicago"
STEP = pd.Timedelta(minutes=15)


def _truth(n_meters: int, start: str, end: str, rng: np.random.Generator) -> pd.DataFrame:
    grid = pd.date_range(start, end, freq="15min", tz="UTC", inclusive="left")
    local = grid.tz_convert(TZ)
    hour = local.hour + local.minute / 60
    frames = []
    for m in range(n_meters):
        scale = rng.uniform(0.6, 1.8)
        shape = 0.2 + 0.4 * np.exp(-((hour - 19) ** 2) / 6) + 0.15 * np.exp(-((hour - 7) ** 2) / 3)
        kwh = scale * shape * (1 + 0.08 * rng.standard_normal(len(grid)))
        frames.append(pd.DataFrame({"meter_id": f"MTR{m:04d}", "interval_start_utc": grid,
                                    "kwh": np.round(np.clip(kwh, 0.005, None), 4)}))
    return pd.concat(frames, ignore_index=True)


def _ending_local(df: pd.DataFrame) -> pd.Series:
    return (df["interval_start_utc"] + STEP).dt.tz_convert(TZ).dt.strftime("%Y-%m-%d %H:%M:%S")


def _local_day_total(truth: pd.DataFrame, day: str) -> float:
    local_day = truth["interval_start_utc"].dt.tz_convert(TZ).dt.strftime("%Y-%m-%d")
    return round(float(truth.loc[local_day == day, "kwh"].sum()), 3)


def task_001(rng: np.random.Generator, out: Path) -> dict:
    """Fall-back DST: interval-ending local labels with the repeated 01:xx hour."""
    truth = _truth(50, "2024-10-27 05:00", "2024-11-10 06:00", rng)
    raw = pd.DataFrame({"meter_id": truth["meter_id"], "read_ts": _ending_local(truth),
                        "kwh": truth["kwh"]})
    raw.to_csv(out / "interval_reads.csv", index=False)
    return {"fleet_kwh_2024_11_03": _local_day_total(truth, "2024-11-03"),
            "intervals_per_meter_2024_11_03": 100,
            "fleet_kwh_2024_11_01_to_09": round(float(sum(
                _local_day_total(truth, f"2024-11-0{d}") for d in range(1, 10))), 3)}


def task_002(rng: np.random.Generator, out: Path) -> dict:
    """Gaps, spikes, and net-metered export mixed with negative errors."""
    truth = _truth(40, "2024-06-01 05:00", "2024-07-01 05:00", rng)
    nem = {f"MTR{m:04d}" for m in range(0, 40, 4)}
    is_nem = truth["meter_id"].isin(nem)
    midday = truth["interval_start_utc"].dt.tz_convert(TZ).dt.hour.between(11, 14)
    kwh = truth["kwh"].where(~(is_nem & midday), -np.round(rng.uniform(0.2, 0.9, len(truth)), 4))
    truth = truth.assign(kwh=kwh)
    raw = truth.assign(read_ts=_ending_local(truth)).copy()
    spikes = rng.choice(raw.index[~is_nem], 25, replace=False)
    neg_err = rng.choice(raw.index[~is_nem & ~midday], 15, replace=False)
    raw.loc[spikes, "kwh"] = 75.0
    raw.loc[neg_err, "kwh"] = -3.0
    gaps = [i for s in rng.choice(raw.index[:-200], 30, replace=False) for i in range(s, s + 3)]
    raw = raw.drop(index=sorted(set(gaps)))
    raw[["meter_id", "read_ts", "kwh"]].to_csv(out / "interval_reads.csv", index=False)
    pd.DataFrame({"meter_id": sorted(truth["meter_id"].unique())}).assign(
        net_metered=lambda d: d["meter_id"].isin(nem),
        service_amps=200, service_volts=240).to_csv(out / "premises.csv", index=False)
    return {"planted_spikes": 25, "planted_negative_errors": 15, "nem_meters": len(nem),
            "fleet_net_kwh_june": round(float(truth["kwh"].sum()), 1),
            "fleet_export_kwh_june": round(float(-truth.loc[truth["kwh"] < 0, "kwh"].sum()), 1)}


def task_003(rng: np.random.Generator, out: Path) -> dict:
    """Cumulative 5-dial registers with rollovers and one meter exchange."""
    truth = _truth(20, "2024-09-01 05:00", "2024-09-15 05:00", rng)
    frames = []
    for i, (mid, g) in enumerate(truth.groupby("meter_id")):
        start = 99_900.0 if i % 3 == 0 else rng.uniform(1_000, 90_000)
        cum = (start + g["kwh"].cumsum().to_numpy()) % 100_000
        frames.append(pd.DataFrame({"meter_id": mid, "read_ts_utc": (
            g["interval_start_utc"] + STEP).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "register_kwh": np.round(cum, 3)}))
    reads = pd.concat(frames, ignore_index=True)
    swap = reads.index[reads["meter_id"] == "MTR0005"]
    cut = swap[len(swap) // 2]
    exchanged = reads.loc[cut:swap[-1], "register_kwh"]
    reads.loc[cut:swap[-1], "register_kwh"] = np.round(exchanged - exchanged.iloc[0] + 3.0, 3)
    reads.to_csv(out / "register_reads.csv", index=False)
    return {"rollover_meters": sorted({f"MTR{m:04d}" for m in range(0, 20, 3)}),
            "exchanged_meter": "MTR0005",
            # The first interval of each meter has no prior register read, so it is excluded.
            "fleet_kwh_true": round(float(truth.groupby("meter_id")["kwh"].apply(
                lambda s: s.iloc[1:].sum()).sum()), 1)}


def task_004(rng: np.random.Generator, out: Path) -> dict:
    """Spring-forward with vendor-bug nonexistent labels and upstream estimated reads."""
    truth = _truth(30, "2024-03-01 06:00", "2024-04-01 05:00", rng)
    raw = truth.assign(read_ts=_ending_local(truth), quality="A").copy()
    est = rng.choice(raw.index, 300, replace=False)
    raw.loc[est, "quality"] = "E"
    bug = raw[raw["read_ts"].str.startswith("2024-03-10 03:")].head(30).copy()
    bug["read_ts"] = bug["read_ts"].str.replace("2024-03-10 03:", "2024-03-10 02:", regex=False)
    raw = pd.concat([raw.drop(bug.index), bug]).sort_index()
    raw[["meter_id", "read_ts", "kwh", "quality"]].to_csv(out / "interval_reads.csv", index=False)
    return {"intervals_per_meter_2024_03_10": 92, "source_estimated_reads": 300,
            "nonexistent_labels": int(len(bug)),
            "fleet_kwh_march": round(float(truth["kwh"].sum()), 1)}


TASKS = {"ami-001": task_001, "ami-002": task_002, "ami-003": task_003, "ami-004": task_004}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True, help="task data (agent-visible)")
    parser.add_argument("--truth-dir", type=Path, required=True, help="answer key (hidden)")
    parser.add_argument("--seed", type=int, default=20241103)
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
