"""Seeded synthetic OMS / CIS data with planted truth for the reliability-metrics eval.

Writes task folders (data only) to $SKILL_EVAL_DATA_DIR (default /tmp/reliability-eval)
and the answer key to $SKILL_EVAL_KEY_DIR (default <data_dir>_answer_key), which must
never be uploaded next to the task data.

    python3 eval/generate_data.py
"""

from __future__ import annotations

import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from reliability_api import build_confirmed_reliability  # noqa: E402
from reliability_core import (  # noqa: E402
    DENOMINATOR_OPTIONS, MED_OPTIONS, PLANNED_OPTIONS, SUSTAINED_THRESHOLD_OPTIONS,
    group_momentary_events,
)

TZ = "America/Denver"
SEED = 20241
YEARS = range(2019, 2025)


def customers_served(base: int = 240_000, monthly_growth: int = 400) -> pd.DataFrame:
    rows = [{"period_start": pd.Timestamp(y, m, 1).date(),
             "customers_served": base + ((y - 2019) * 12 + m - 1) * monthly_growth}
            for y in YEARS for m in range(1, 13)]
    return pd.DataFrame(rows)


def _event_steps(rng, event_id: str, start: pd.Timestamp, planned: bool) -> list[dict]:
    """1-4 restoration steps; first step sometimes inside 5 minutes (momentary)."""
    n_steps = int(rng.integers(1, 5))
    offsets = np.sort(rng.gamma(2.0, 45.0, n_steps)) + 1.0
    if rng.random() < 0.3:
        offsets[0] = float(rng.uniform(0.5, 4.5))
    customers = rng.integers(20, 400, n_steps)
    cause = "PLANNED" if planned else str(rng.choice(["VEG", "EQUIP", "ANIMAL", "WEATHER", "UNK"]))
    return [{"event_id": event_id, "outage_start": start,
             "restore_ts": start + pd.Timedelta(minutes=float(o)),
             "customers_restored": int(c), "cause_code": cause, "is_planned": planned,
             "circuit_id": f"FDR{int(rng.integers(1, 41)):03d}"}
            for o, c in zip(offsets, customers)]


def history_steps(rng) -> pd.DataFrame:
    rows = []
    for day in pd.date_range(f"{YEARS[0]}-01-01", f"{YEARS[-1]}-12-31", freq="D"):
        for k in range(int(rng.poisson(3))):
            local = (day + pd.Timedelta(minutes=float(rng.uniform(0, 1439)))).tz_localize(
                TZ, nonexistent="shift_forward", ambiguous=False)
            rows.extend(_event_steps(rng, f"E{day:%Y%m%d}{k}", local, rng.random() < 0.08))
    return pd.DataFrame(rows)


def plant_storm(rng, steps: pd.DataFrame, day: str) -> pd.DataFrame:
    """Late-evening local storm: in UTC it falls on the next calendar day."""
    start = pd.Timestamp(f"{day} 19:30").tz_localize(TZ)
    rows = []
    for k in range(60):
        rows.extend(_event_steps(rng, f"STORM{k}", start + pd.Timedelta(minutes=k * 4), False))
    storm = pd.DataFrame(rows).assign(
        restore_ts=lambda d: d["restore_ts"] + pd.Timedelta(hours=6),
        customers_restored=lambda d: d["customers_restored"] * 3)
    return pd.concat([steps, storm], ignore_index=True)


def recloser_ops(rng) -> pd.DataFrame:
    rows = []
    for i in range(300):
        t0 = pd.Timestamp("2024-01-01", tz=TZ) + pd.Timedelta(minutes=float(rng.uniform(0, 525_000)))
        device, cust = f"RCL{int(rng.integers(1, 30)):02d}", int(rng.integers(50, 900))
        for shot in range(int(rng.integers(1, 4))):
            rows.append({"device_id": device, "op_ts": t0 + pd.Timedelta(seconds=30 * shot),
                         "customers_affected": cust})
    return pd.DataFrame(rows)


def scenario_truth(steps, customers) -> list[dict]:
    out = []
    for combo in itertools.product(SUSTAINED_THRESHOLD_OPTIONS, DENOMINATOR_OPTIONS,
                                   PLANNED_OPTIONS, MED_OPTIONS):
        decisions = dict(zip(("sustained_threshold_min", "denominator_basis",
                              "planned_handling", "med_method"), combo))
        res = build_confirmed_reliability(steps, customers, 2024, TZ, **decisions)
        out.append({"decisions": decisions,
                    "all_days": _pick(res["all_days"]), "excluding_med": _pick(res["excluding_med"]),
                    "major_event_days": [str(d) for d in res["major_event_days"]],
                    "t_med_minutes": res["med_stats"].get("t_med_minutes")})
    return out


def _pick(r: dict) -> dict:
    return {k: r[k] for k in ("saidi_min", "saifi", "caidi_min", "maifi")}


def _write(df: pd.DataFrame, folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    ts_cols = [c for c in df.columns if c in ("outage_start", "restore_ts", "op_ts")]
    df.assign(**{c: df[c].map(lambda t: t.isoformat()) for c in ts_cols}).to_csv(
        folder / name, index=False)


def main() -> int:
    data_dir = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "/tmp/reliability-eval"))
    key_dir = Path(os.environ.get("SKILL_EVAL_KEY_DIR", f"{data_dir}_answer_key"))
    rng = np.random.default_rng(SEED)
    customers = customers_served()
    steps = plant_storm(rng, history_steps(rng), "2024-08-10")
    ops = recloser_ops(rng)
    for task in ("task_001", "task_002", "task_003", "task_005"):
        _write(steps, data_dir / task, "restoration_steps.csv")
        customers.to_csv(data_dir / task / "customers_served.csv", index=False)
    _write(ops, data_dir / "task_004", "recloser_operations.csv")
    customers.to_csv(data_dir / "task_004" / "customers_served.csv", index=False)
    n_t = float(customers.loc[pd.to_datetime(customers["period_start"]).dt.year == 2024,
                              "customers_served"].mean())
    truth = {"timezone": TZ, "planted_storm_local_day": "2024-08-10",
             "scenarios": scenario_truth(steps, customers),
             "maifi_e_average_basis": float(group_momentary_events(ops)["customers_affected"].sum()) / n_t,
             "momentary_events": int(len(group_momentary_events(ops)))}
    key_dir.mkdir(parents=True, exist_ok=True)
    (key_dir / "truth.json").write_text(json.dumps(truth, indent=2))
    print(f"wrote task data to {data_dir} and answer key to {key_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
