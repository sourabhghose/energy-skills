"""Generate seeded synthetic grid-data-guard eval datasets with planted truth.

Task data goes to ``--out-dir/<task_id>/`` (agent-visible); the answer key goes to
``--truth-dir/truth.json`` and must never be uploaded next to the task data.

    python eval/generate_data.py --out-dir /tmp/gdg-eval/tasks --truth-dir /tmp/gdg-eval/truth
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ZIP_SIZES = {"94101": 120, "94102": 80, "94103": 40, "94104": 9, "94105": 30}
DOMINATED_ZIP = "94105"
MONTHS = pd.date_range("2024-01-01", periods=6, freq="MS")


def _customers(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for z, n in ZIP_SIZES.items():
        for i in range(n):
            rows.append({"premise_id": f"P{z}{i:04d}", "account_number": f"{rng.integers(1e9, 1e10)}",
                         "customer_name": f"Customer {z}-{i}", "service_address": f"{10 + i} Market St",
                         "zip": z, "rate_class": "RES" if i % 7 else "SGS",
                         "lat": round(37.77 + rng.normal(0, 0.01), 6),
                         "lon": round(-122.42 + rng.normal(0, 0.01), 6)})
    return pd.DataFrame(rows)


def _usage(cust: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    frames = [cust.assign(read_month=m.strftime("%Y-%m-%d"),
                          kwh=np.round(rng.gamma(4, 120, len(cust)), 1)) for m in MONTHS]
    usage = pd.concat(frames, ignore_index=True)
    big = usage["premise_id"] == f"P{DOMINATED_ZIP}0000"
    return usage.assign(kwh=usage["kwh"].where(~big, 90_000.0), rate_class=usage["rate_class"].where(
        ~big, "LGS"))


def task_001(rng, out: Path) -> dict:
    """Public monthly-usage-by-ZIP release: one small ZIP, one dominated ZIP."""
    usage = _usage(_customers(rng), rng)
    usage.to_csv(out / "monthly_usage.csv", index=False)
    released = sorted(z for z, n in ZIP_SIZES.items() if n >= 15 and z != DOMINATED_ZIP)
    return {"released_zips": released, "suppressed_zips": ["94104", DOMINATED_ZIP],
            "released_cells": len(released) * len(MONTHS)}


def task_002(rng, out: Path) -> dict:
    """Column classification on a GIS/asset extract with misnamed sensitive columns."""
    n = 60
    df = pd.DataFrame({
        "asset_id": [f"A{i:05d}" for i in range(n)],
        "asset_type": rng.choice(["pole", "transformer", "switch"], n),
        "feeder": rng.choice(["F101", "F102"], n),
        "substation_name": "Mission",
        "relay_pickup_a": rng.choice([300, 450], n),
        "notes": [f"10.20.{i % 5}.{i}" for i in range(n)],
        "contact": [f"(415) 555-{1000 + i}" for i in range(n)],
        "install_year": rng.integers(1970, 2020, n),
        "latitude": np.round(37.7 + rng.normal(0, 0.02, n), 6),
        "longitude": np.round(-122.4 + rng.normal(0, 0.02, n), 6),
        "condition_score": rng.integers(1, 6, n),
    })
    df.to_csv(out / "assets.csv", index=False)
    return {"ceii_columns": ["feeder", "substation_name", "relay_pickup_a", "notes"],
            "pii_columns": ["contact"], "geo_columns": ["latitude", "longitude"],
            "non_sensitive": ["asset_id", "asset_type", "install_year", "condition_score"]}


def task_003(rng, out: Path) -> dict:
    """Internal analyst view over customer usage: tokens must be salted."""
    usage = _usage(_customers(rng), rng)
    usage.to_csv(out / "monthly_usage.csv", index=False)
    return {"must_tokenize": ["account_number", "premise_id"],
            "must_hide": ["customer_name", "service_address", "lat", "lon"]}


def task_004(rng, out: Path) -> dict:
    """ZIP cells plus a published monthly total: exactly one small ZIP → complementary cell."""
    cust = _customers(rng)
    cust = cust[cust["zip"] != DOMINATED_ZIP]
    usage = _usage(cust, rng)
    usage.to_csv(out / "monthly_usage.csv", index=False)
    totals = usage[usage["zip"] != "94104"].groupby(["read_month", "zip"])["kwh"].sum()
    smallest = totals.groupby(level=0).idxmin().map(lambda t: t[1])
    return {"primary_suppressed_zip": "94104",
            "complementary_suppressed_by_month": smallest.to_dict(),
            "released_cells": 2 * len(MONTHS)}


TASKS = {"gdg-001": task_001, "gdg-002": task_002, "gdg-003": task_003, "gdg-004": task_004}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True, help="task data (agent-visible)")
    parser.add_argument("--truth-dir", type=Path, required=True, help="answer key (hidden)")
    parser.add_argument("--seed", type=int, default=1515)
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
