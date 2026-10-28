"""Generate seeded synthetic data for the unit-guard benchmark.

Writes task inputs to $SKILL_EVAL_DATA_DIR/task_00N/ and the planted truth to
$SKILL_EVAL_DATA_DIR/_answer_key/ (never upload _answer_key to the agent's volume).

    SKILL_EVAL_DATA_DIR=/tmp/unit-guard-eval python3 eval/generate_data.py
"""

from __future__ import annotations

import csv
import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SEED = 20261028
SCF_TO_SM3_60F_14696 = 0.028316846592 * (288.15 / 288.705556)


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def task_001(root: Path, rng: random.Random) -> dict:
    """Daily gas (Mcf/d) and oil (bbl/d) for 3 wells, 90 days; ask for MSm3 and boe."""
    rows, gas_total, oil_total = [], 0.0, 0.0
    start = datetime(2026, 1, 1)
    for well in ("42-123-45678", "42-123-45679", "42-123-45680"):
        for day in range(90):
            gas = round(rng.uniform(800, 2500) * (0.995 ** day), 1)
            oil = round(rng.uniform(150, 600) * (0.994 ** day), 1)
            gas_total, oil_total = gas_total + gas, oil_total + oil
            rows.append([well, (start + timedelta(days=day)).date().isoformat(), gas, oil])
    _write_csv(root / "task_001" / "daily_production.csv", ["api14", "date", "gas_mcfd", "oil_bopd"], rows)
    (root / "task_001" / "gas_sales_contract_excerpt.txt").write_text(
        "Section 4.2 Measurement. Volumes are stated in standard cubic feet at a base temperature "
        "of sixty degrees Fahrenheit (60 F) and a base pressure of 14.696 pounds per square inch "
        "absolute.\n")
    return {
        "gas_total_msm3_60F_14.696": gas_total * 1e3 * SCF_TO_SM3_60F_14696 / 1e6,
        "boe_total_6_to_1": oil_total + gas_total / 6.0,
        "scf_basis_in_contract": "60F_14.696psia",
    }


def task_002(root: Path, rng: random.Random) -> dict:
    """15-minute plant MW readings across the 2026-03-08 US spring-forward day (local time)."""
    tz = ZoneInfo("America/Chicago")
    start = datetime(2026, 3, 7, tzinfo=tz)
    rows, energy = [], 0.0
    t = start.astimezone(ZoneInfo("UTC"))
    end = datetime(2026, 3, 10, tzinfo=tz).astimezone(ZoneInfo("UTC"))
    while t < end:
        mw = round(rng.uniform(180, 420), 2)
        energy += mw * 0.25
        rows.append([t.astimezone(tz).isoformat(), mw])
        t += timedelta(minutes=15)
    _write_csv(root / "task_002" / "plant_output_15min.csv", ["interval_start_local", "output_mw"], rows)
    return {"energy_mwh": energy, "intervals": len(rows), "intervals_on_2026_03_08": 92}


def task_003(root: Path, rng: random.Random) -> dict:
    """Facility emissions with ambiguous 'tons' columns; truth assumes short tons + AR5."""
    rows, total = [], 0.0
    for i in range(12):
        co2, ch4, n2o_lb = rng.uniform(5e3, 9e3), rng.uniform(10, 40), rng.uniform(200, 900)
        rows.append([f"2025-{i + 1:02d}", round(co2, 2), round(ch4, 3), round(n2o_lb, 1)])
        st = 0.90718474
        total += round(co2, 2) * st + round(ch4, 3) * st * 28 + round(n2o_lb, 1) * 0.45359237e-3 * 265
    _write_csv(root / "task_003" / "facility_emissions.csv", ["month", "co2_tons", "ch4_tons", "n2o_lb"], rows)
    (root / "task_003" / "README.txt").write_text(
        "Emissions exported from a US plant historian. Units as labelled by the source system.\n")
    return {"total_tco2e_if_short_tons_ar5": total, "ton_type_truth": "short_ton"}


def main() -> None:
    root = Path(os.environ.get("SKILL_EVAL_DATA_DIR", "/tmp/unit-guard-eval"))
    rng = random.Random(SEED)
    truth = {"ug-001": task_001(root, rng), "ug-002": task_002(root, rng), "ug-003": task_003(root, rng)}
    key = root / "_answer_key" / "truth.json"
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_text(json.dumps(truth, indent=2))
    print(f"Wrote tasks to {root} and answer key to {key}")


if __name__ == "__main__":
    main()
